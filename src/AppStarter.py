from http import HTTPStatus

import uvicorn
from asgiref.wsgi import WsgiToAsgi
from flask import Flask, Response, request
from telegram.ext import Application

from telegram import Update


def get_telegram_application(token: str, base_url: str) -> Application:
    return (Application.builder()
            .token(token)
            .base_url(f"{base_url}/bot")
            .base_file_url(f"{base_url}/file/bot")
            .updater(None)
            .build())

def get_webserver(server_port: int, host: str, telegram_application) -> uvicorn.Server:
    flask_app = Flask(__name__)

    @flask_app.post("/telegram")
    async def telegram() -> Response:
        await telegram_application.update_queue.put(Update.de_json(data=request.json, bot=telegram_application.bot))
        return Response(status=HTTPStatus.OK)

    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=WsgiToAsgi(flask_app),
            port=server_port,
            use_colors=False,
            host=host
        )
    )
    return webserver