import QtQuick 2.7
import QtGraphicalEffects 1.0
import QtQuick.Controls 2.3
import QtQuick.Layouts 1.3

//import "UI" as UI


GridView {
    id: root
    clip: true
    property int gap
    property int margin: 4
    //property string selectedGameID
    //signal gameSelected(var game)
    flickDeceleration: 9000
    maximumFlickVelocity: 6000
    topMargin: 20
    bottomMargin: height - cellHeight - 20
    cellWidth: 128 + gap; cellHeight: 128 + gap

    ScrollBar.vertical: ScrollBar {
        width: 20
    }

    Component {
        id: highlightGlow
        Rectangle {
            width: 128 + margin * 2
            height: 128 + margin * 2
            x: root.currentItem !== null ? root.currentItem.x + gap / 2 - margin : 0
            y: root.currentItem !== null ? root.currentItem.y - margin : 0
            //color: "#def"
            color: "transparent"
            border.width: 2
            border.color: "#fff"
            z: 10
        }
    }
    highlight: highlightGlow
    highlightFollowsCurrentItem: false

    delegate: Column {
        spacing: 10
        rightPadding: gap/2; leftPadding: gap/2
        Rectangle {
            id: thumbBg
            width: 128; height: 128
            color: "transparent"
            Rectangle {
                color: "#7766bbff"
                //border.width: 2
                //border.color: "#"
                anchors.fill: parent
                //x: image.x + image.width / 2 - image.paintedWidth / 2
                //y: image.y + image.height / 2 - image.paintedHeight / 2
                //width: image.paintedWidth
                //height: image.paintedHeight

                anchors.margins: -margin
                //glowRadius: 6
                //spread: 0.2
                
                visible: model.modelData.selected
            }
            Image {
                id: image
                anchors.fill: parent
                width: 128
                sourceSize.width: 128
                sourceSize.height: 128
                asynchronous: true
                mipmap: true
                fillMode: Image.PreserveAspectFit
                source: model.modelData.path
            }
            MouseArea {
                id: mouseBox
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                hoverEnabled: true
                onClicked: {
                    backend.updateSelection(mouse.modifiers, root.currentIndex, index)

                    //var start = -1, end = -1;
                    //if (mouse.modifiers & Qt.ShiftModifier) {
                        //if (root.currentIndex > index) {
                            //start = index; end = root.currentIndex
                        //} else if (root.currentIndex < index) {
                            //start = root.currentIndex; end = index
                        //}
                        ////if (start >= 0) {
                            ////for (var i = start; i <= end; i++) {
                                ////backend.imageModel[i].selected = true
                            ////}
                        ////}
                    //}
                    //for (var i = 0; i < backend.imageModel.length; i++) {
                        //if (start >= 0 && i >= start && i <= end) {
                            //backend.imageModel[i].selected = true
                        //} else if (backend.imageModel[i].selected) {
                            //backend.imageModel[i].selected = false
                        //}
                    //}
                    root.currentIndex = index
                }
            }
        }
    }
}
