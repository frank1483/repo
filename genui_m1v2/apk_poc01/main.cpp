// APK 最小測試包的主程式：載入資源裡的 demo_main.qml（qrc:/genui/apk_poc01/demo_main.qml）。桌面也能跑，給 -I 參數時改載入指定檔。
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QUrl>
int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    QQmlApplicationEngine engine;
    engine.addImportPath(QStringLiteral("qrc:/qml"));
    QObject::connect(&engine, &QQmlApplicationEngine::exit, &app, &QCoreApplication::exit, Qt::QueuedConnection);
    engine.load(argc >= 2 ? QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])) : QUrl(QStringLiteral("qrc:/genui/apk_poc01/demo_main.qml")));
    if (engine.rootObjects().isEmpty()) return 4;
    return app.exec();
}
