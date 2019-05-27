import QtQuick 2.7


Rectangle {
    property alias drag: mouseArea.drag
    property bool vertical: true
    id: slider
    width: 10
    height: 10
    z: 200
    color: "#555"
    MouseArea {
        id: mouseArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        cursorShape: vertical ? Qt.SizeHorCursor : Qt.SizeVerCursor
        drag.axis: vertical ? Drag.XAxis : Drag.YAxis
        drag.smoothed: false
        drag.target: slider
        drag.threshold: 0
        hoverEnabled: true
    }
    MouseArea {
        id: cursorShaper
        cursorShape: vertical ? Qt.SizeHorCursor : Qt.SizeVerCursor
        acceptedButtons: Qt.NoButton
        width: 0
        height: 0
        enabled: false
        hoverEnabled: false
        states: [
            State {
                when: mouseArea.drag.active
                PropertyChanges {
                    target: cursorShaper
                    x: mouseArea.mouseX - 50
                    y: mouseArea.mouseY - 50
                    width: 100
                    height: 100
                    hoverEnabled: true
                }
            }
        ]
    }
    states: [
        State {
            when: mouseArea.drag.active || mouseArea.containsMouse
            PropertyChanges {
                target: slider
                color: "#999"
            }
        }
    ]
}
