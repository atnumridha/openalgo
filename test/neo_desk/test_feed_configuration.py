from types import SimpleNamespace
from dotenv import dotenv_values
from scripts.setup_neo_instance import provision
def test_browser_stream_url_matches_the_isolated_proxy_port(tmp_path,monkeypatch):
    (tmp_path/'frontend').mkdir();(tmp_path/'.sample.env').write_text("WEBSOCKET_URL='ws://127.0.0.1:8765'\n")
    monkeypatch.setattr('scripts.setup_neo_instance.read_saved_kotak_settings',lambda p:SimpleNamespace(ucc='fixture',api_token='fixture',mobile='fixture',mpin='fixture',access_secret='fixture'))
    monkeypatch.setattr('scripts.setup_neo_instance.load_dotenv',lambda *a,**k:None)
    provision(tmp_path,tmp_path)
    env=dotenv_values(tmp_path/'.env')
    assert env['WEBSOCKET_URL']=='ws://127.0.0.1:'+env['WEBSOCKET_PORT']
