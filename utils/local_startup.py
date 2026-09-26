"""Restrict detached desktop use of the development server to loopback."""


def local_server_options(host, debug, enabled):
    if enabled != "1":
        return {}
    if host not in {"127.0.0.1", "localhost", "::1"} or debug:
        raise ValueError("Local desktop startup requires a loopback address and FLASK_DEBUG=False")
    # Flask-SocketIO requires explicit opt-in without an interactive terminal.
    # This is for the local desktop launcher, never a public server deployment.
    return {"allow_unsafe_werkzeug": True, "use_reloader": False}
