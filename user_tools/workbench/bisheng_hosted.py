"""Run the complete workstation inside a BiSheng managed application instance."""

from http.server import ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import urlsplit

from bisheng_sdk import auth
from bisheng_sdk.errors import PlatformIdentityMissingError

from user_tools.workbench.server import APP_VERSION, Application, Handler


class HostedHandler(Handler):
    def authorized(self):
        try:
            user = auth.from_headers(dict(self.headers.items()))
        except PlatformIdentityMissingError:
            return False
        return bool(user.app_id and user.app_id == os.environ.get("BISHENG_APP_ID"))

    def do_GET(self):
        if urlsplit(self.path).path == "/health":
            self.json({"status": "ok", "application": "fangzhen", "version": APP_VERSION})
            return
        super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path in ("/api/shutdown", "/api/open_folder"):
            self.json({"error": "请在毕昇应用中心管理应用和查看已保存文件。"}, 400)
            return
        super().do_POST()


def main():
    project = Path(__file__).resolve().parents[2]
    database = Path(os.environ.get("BISHENG_APP_DB_PATH", "/data/app.db"))
    data = database.parent
    for name in ("project-data", "project-outputs", "logs", "workbench"):
        (data / name).mkdir(parents=True, exist_ok=True)
    application = Application(data / "workbench", project, database_path=database)
    application.deployment_mode = "bisheng"
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), HostedHandler)
    server.app = application
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
