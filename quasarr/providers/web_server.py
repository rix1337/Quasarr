# -*- coding: utf-8 -*-
# Quasarr
# Project by https://github.com/rix1337

import time
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

temp_server_success = False


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class NoLoggingWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


class Server:
    def __init__(self, wsgi_app, listen='127.0.0.1', port=8080):
        self.wsgi_app = wsgi_app
        self.listen = listen
        self.port = port
        self.server = make_server(self.listen, self.port, self.wsgi_app,
                                  ThreadingWSGIServer, handler_class=NoLoggingWSGIRequestHandler)

    def serve_temporarily(self):
        global temp_server_success
        self.server.timeout = 1
        try:
            while not temp_server_success:
                self.server.handle_request()
            self.server.handle_request()  # handle the last request
        except Exception:
            self.server.server_close()
            return False
        time.sleep(1)
        self.server.server_close()
        temp_server_success = False
        return True

    def serve_forever(self):
        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            self.server.shutdown()
            self.server.server_close()
