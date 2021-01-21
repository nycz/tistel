import mimetypes
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Optional, Set, Tuple

_PNG_MAGIC = b'\x89PNG\x0d\x0a\x1a\x0a'
_JPEG_MAGIC = b'\xff\xd8'

IMAGE_EXTS = ('.png', '.jpg', '.gif')
IMAGE_MAGICS = ([_PNG_MAGIC],
                [_JPEG_MAGIC],
                [b'GIF87a', b'GIF89a'])


NS = {'x': 'adobe:ns:meta/',
      'xmp': 'http://ns.adobe.com/xap/1.0/',
      'xmpRights': 'http://ns.adobe.com/xap/1.0/rights/',
      'xmpMM': 'http://ns.adobe.com/xap/1.0/mm/',
      'xmpidq': 'http://ns.adobe.com/xmp/Identifier/qual/1.0/',
      'stRef': 'http://ns.adobe.com/xap/1.0/sType/ResourceRef#',
      'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
      'dc': 'http://purl.org/dc/elements/1.1/'}


class ImageError(Exception):
    pass


def image_format_mismatch(fname: Path, fmt: str) -> bool:
    return mimetypes.guess_type(fname)[0] != fmt


def identify_image_format(fname: Path) -> Optional[str]:
    with open(fname, 'rb') as f:
        data = f.read(8)
    if data == _PNG_MAGIC:
        return 'image/png'
    elif data[:2] == _JPEG_MAGIC:
        return 'image/jpeg'
    elif data[:3] == b'GIF':
        if data[3:6] == b'89a':
            return 'image/gif'
        else:
            raise ImageError(f'Unsupported GIF format: {data[3:6]!r}')
    return None


def dimensions(fname: Path) -> Tuple[int, int]:
    try:
        text = subprocess.check_output(['exiv2', '-p', 's', str(fname)],
                                       stderr=subprocess.PIPE,
                                       encoding='utf-8')
    except subprocess.CalledProcessError as e:
        text = e.stdout
    size_lines = [(int(m[1]), int(m[2])) for line in text.splitlines()
                  if (m := re.fullmatch(r'Image size\s*:\s*(\d+)\s*x\s*(\d+)\s*', line))]
    if size_lines:
        return size_lines[0]
    return (-1, -1)


def read_tags(fname: Path) -> Iterable[str]:
    try:
        result = subprocess.check_output(['exiv2', '-p', 'X', str(fname)],
                                         stderr=subprocess.PIPE, encoding='utf-8')
    except subprocess.CalledProcessError as e:
        pass
    else:
        if not result.strip():
            return
        root = ET.fromstring(result)
        yield from (
            tag for raw_tag
            in root.findall('rdf:RDF/rdf:Description/dc:subject'
                            '/rdf:Bag/rdf:li', NS)
            if (tag := (raw_tag.text or '').strip())
        )


def set_tags(fname: Path, tags: Set[str]) -> None:
    tt = 'Xmp.dc.subject'
    args = ['exiv2', '-M', f'del {tt}']
    for tag in tags:
        args.extend(['-M', f'set {tt} {tag}'])
    args.append(str(fname))
    try:
        result = subprocess.check_output(args, stderr=subprocess.PIPE,
                                         encoding='utf-8')
    except subprocess.CalledProcessError as e:
        stderr: str = e.stderr
        raise ImageError(f'running exiv2 failed on image {fname!r}!\n'
                         f'stderr: {stderr!r}')
    else:
        if result:
            print(f'\x1b[31mWarnings when tags added to file {fname!r}\x1b[0m')
            print(result)
        return
