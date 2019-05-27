import QtQuick 2.7
import QtQuick.Controls 2.3
import QtQuick.Layouts 1.3

Dialog {
    id: taggingDialog
    title: "Tag " + backend.selectedImages.length + " images"
    //standardButtons: Dialog.Close
    width: 400
    height: 500
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
    Item {
        anchors.fill: parent
        //spacing: 10
        //height: 200
        TextField {
            id: tagInput
            //height: 20
            //color: "white"
            font.pointSize: 14
            //font.bold: true
            placeholderText: "Search for tags"
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
        }
        ListView {
            id: tagSuggestions
            anchors.top: tagInput.bottom
            anchors.left: tagInput.left
            model: backend.tagSuggestions
            clip: true
            delegate: Text {
                text: model.modelData
            }
            z: 10
            //text: backend.tag
        }
        ListView {
            anchors.top: tagInput.bottom
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            //height: 200
            spacing: 10
            model: backend.selectedTags
            delegate: Row {
                property int total: backend.selectedImages.length
                property int tagged: model.modelData !== null ? model.modelData.count : 0
                spacing: 10
                height: 20
                CheckBox {
                    //tristate: true
                    checkState: tagged === total ? Qt.Checked : tagged === 0 ? Qt.Unchecked : Qt.PartiallyChecked
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    verticalAlignment: Text.AlignVCenter
                    color: "white"
                    text: model.modelData !== null ? model.modelData.name : ""
                }
            }
        }
    }
}
