// genui 驗證用小主程式：把正式 QGroundControl.GCP 的 11 個 QML 檔與字型編進程式資源（qrc:/qml/...），讓 FontLoader 能載入正式字型。
// 用法：genui_host <驗證 QML 檔>。只給驗證用，不是 GCS 主程式。
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QUrl>
int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    if (argc < 2) { qCritical("usage: genui_host <file.qml>"); return 2; }
    QQmlApplicationEngine engine;
    engine.addImportPath(QStringLiteral("qrc:/qml"));
    QObject::connect(&engine, &QQmlApplicationEngine::exit, &app, &QCoreApplication::exit, Qt::QueuedConnection);
    QObject::connect(&engine, &QQmlApplicationEngine::quit, &app, &QCoreApplication::quit, Qt::QueuedConnection);
    engine.load(QUrl::fromLocalFile(QString::fromLocal8Bit(argv[1])));
    if (engine.rootObjects().isEmpty()) return 4;
    return app.exec();
}
