import QtQuick 2.7
import QtQuick.Controls 2.3
import QtQuick.Dialogs 1.0
import Qt.labs.platform 1.0 as Labs
import QtQuick.Layouts 1.3
import QtQuick.Window 2.2
//import "UI" as UI
//import "DetailViews" as DetailViews
import Tag 1.0

ApplicationWindow {
    id: root
    visible: true
    color: "#222"
    property var gap: 24

    Rectangle {
        id: tabview
        anchors.left: parent.left
        anchors.right: slider1.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        color: "#111"
        
        TabBar {
            id: bar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            TabButton { text: "Tags" }
            TabButton { text: "Files" }
            TabButton { text: "Dates" }
        }

        StackLayout {
            currentIndex: bar.currentIndex
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: bar.bottom
            anchors.bottom: hslider.bottom
            ListView {
                id: tagView
                clip: true
                model: backend.tagsModel
                delegate: Item {
                    height: 24
                    anchors.left: parent.left
                    anchors.right: parent.right
                    Text {
                        id: tagText
                        color: model.modelData.state === Tag.Whitelisted ? "#8f8" : model.modelData.state === Tag.Blacklisted ? "#f88" : "#eee"
                        font.pixelSize: 16
                        anchors.left: parent.left
                        //anchors.top: parent.top
                        //anchors.topMargin: 10
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: model.modelData.name
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        onClicked: {
                            if (model.modelData.state !== Tag.Inactive) {
                                model.modelData.state = Tag.Inactive
                            } else if (mouse.button === Qt.LeftButton) {
                                model.modelData.state = Tag.Whitelisted
                            } else if (mouse.button === Qt.RightButton) {
                                model.modelData.state = Tag.Blacklisted
                            }
                        }
                    }
                }
            }
            Rectangle {
                color: "green"
            }
            Rectangle {
                color: "cyan"
            }
        }

        SizerHandle {
            id: hslider
            y: parent.height * 0.8
            vertical: false
            anchors.left: parent.left
            anchors.right: parent.right
        }

        Rectangle {
            color: "#111"
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: hslider.bottom
            anchors.bottom: settingsButtonRow.top
            ColumnLayout {
                anchors.fill: parent
                Text {
                    color: "#eee"
                    font.pointSize: 16
                    wrapMode: Text.WrapAnywhere
                    text: backend.imageModel.length > 0 ? backend.imageModel[thumbview.currentIndex].fullPath : ""
                    Layout.fillWidth: true
                }
                ListView {
                    height: 100
                    Layout.fillWidth: true
                    model: backend.imageModel.length > 0 ? backend.imageModel[thumbview.currentIndex].tags : []
                    delegate: Text {
                        color: "#eee"
                        font.pointSize: 16
                        width: 100
                        wrapMode: Text.WrapAnywhere
                        text: model.modelData

                    }
                }
            }
        }
        Row {
            id: settingsButtonRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            Button {
                text: "Settings"
                onClicked: settings.open()
            }
        }
    }

    SizerHandle {
        id: slider1
        x: 300
        drag.minimumX: 150
        drag.maximumX: slider2.x - 50
        anchors.top: parent.top
        anchors.bottom: parent.bottom
    }

    ThumbView {
        id: thumbview
        anchors.left: slider1.right
        anchors.right: slider2.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        gap: root.gap
        model: backend.imageModel
    }

    SizerHandle {
        id: slider2
        x: 1300
        drag.minimumX: slider1.x + slider1.width + 50
        anchors.top: parent.top
        anchors.bottom: parent.bottom
    }

    Rectangle {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.left: slider2.right
        anchors.right: parent.right
        color: "black"
        Image {
            anchors.fill: parent
            asynchronous: true
            mipmap: true
            fillMode: Image.PreserveAspectFit
            source: backend.imageModel[thumbview.currentIndex] !== undefined ? backend.imageModel[thumbview.currentIndex].fullPath : ""
        }
        MouseArea {
            anchors.fill: parent
            onWheel: {
                var oldIndex = thumbview.currentIndex
                if (wheel.angleDelta.y < 0) {
                    if (thumbview.currentIndex === thumbview.count - 1) {
                        thumbview.currentIndex = 0
                    } else {
                        thumbview.currentIndex += 1
                    }
                } else {
                    if (thumbview.currentIndex === 0) {
                        thumbview.currentIndex = thumbview.count - 1
                    } else {
                        thumbview.currentIndex -= 1
                    }
                }
                backend.updateSelection(0, oldIndex, thumbview.currentIndex)
            }
        }
    }

    Dialog {
        id: settings
        title: "Settings"
        //standardButtons: Dialog.Close
        width: 800
        //height: 
        dim: true
        modal: true
        leftMargin: (parent.width - width) / 2
        topMargin: (parent.height - height) / 2
        padding: 20
        background: Rectangle {
            border.width: 2
            border.color: "black"
            color: "#112"
        }
        footer: DialogButtonBox {
            background: Rectangle {
                color: "green"
            }
            Button {
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
                text: "Close"
            }
        }
        ColumnLayout {
            //spacing: 10
            Text {
                color: "white"
                font.pointSize: 16
                font.bold: true
                text: "Image directories"
            }
            ListView {
                height: 200
                spacing: 10
                model: backend.imageDirectories
                delegate: Row {
                    spacing: 10
                    height: 40
                    Button {
                        background: Rectangle {
                            color: "#bbb"
                        }
                        text: "-"
                        onClicked: backend.removeDirectory(model.modelData)
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        verticalAlignment: Text.AlignVCenter
                        color: "white"
                        text: model.modelData
                    }
                }
            }
            Button {
                text: "Add directory..."
                onClicked: fileDirectoryDialog.open()
            }
        }
    }
    FileDialog {
        id: fileDirectoryDialog
        title: "Choose a directory"
        folder: shortcuts.pictures
        selectFolder: true
        onAccepted: {
            backend.addDirectory(fileDirectoryDialog.folder)
        }
    }
    TagDialog {
        id: taggingDialog
    }


    Shortcut {
        sequence: "Escape"
        context: Qt.ApplicationShortcut
        onActivated: Qt.callLater(Qt.quit)
    }
    Shortcut {
        sequence: "Ctrl+T"
        context: Qt.ApplicationShortcut
        onActivated: taggingDialog.open()
    }
}
