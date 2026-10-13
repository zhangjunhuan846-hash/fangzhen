"""Local settings for the optional OpenAI-compatible battery agent endpoint."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def settings_path(project):
    return Path(project) / 'data' / 'agent_llm.local.json'


def validate_endpoint(base_url, model):
    if not isinstance(base_url, str) or not isinstance(model, str):
        raise ValueError('API地址和模型名需为文本。')
    base_url = base_url.strip().rstrip('/')
    model = model.strip()
    if not base_url or len(base_url) > 500 or not model or len(model) > 200:
        raise ValueError('请填写有效的API地址和模型名。')
    try:
        url = urlsplit(base_url)
        port = url.port
    except ValueError:
        raise ValueError('API端口无效。') from None
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise ValueError('API地址不得包含凭据、查询或片段。')
    loopback = url.hostname in ('localhost', '127.0.0.1', '::1')
    if url.scheme != 'https' and not (url.scheme == 'http' and loopback):
        raise ValueError('远程API需HTTPS；本机localhost可使用HTTP。')
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('API端口需在1–65535之间。')
    if url.path.endswith('/chat/completions'):
        raise ValueError('请填写基础地址，例如https://服务域名/v1，不要附加/chat/completions。')
    return base_url, model


def public_settings(project):
    path = settings_path(project)
    if not path.is_file():
        return {'configured': False, 'base_url': '', 'model': '', 'has_api_key': False}
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        base_url, model = validate_endpoint(data['base_url'], data['model'])
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError):
        return {'configured': False, 'base_url': '', 'model': '', 'has_api_key': False,
                'error': '本机配置无效，请重新填写。'}
    return {'configured': True, 'base_url': base_url, 'model': model,
            'has_api_key': bool(data.get('api_key'))}


def save_settings(project, payload):
    if not isinstance(payload, dict):
        raise ValueError('API配置需为对象。')
    base_url, model = validate_endpoint(payload.get('base_url'), payload.get('model'))
    provided = payload.get('api_key', '')
    if not isinstance(provided, str) or len(provided) > 4096:
        raise ValueError('API密钥格式无效。')
    old = settings_path(project)
    prior = {}
    if old.is_file():
        try:
            prior = json.loads(old.read_text(encoding='utf-8-sig'))
        except (ValueError, OSError):
            pass
    if payload.get('clear_key') is True:
        key = ''
    else:
        key = provided if provided else prior.get('api_key', '')
    old.parent.mkdir(parents=True, exist_ok=True)
    temp = old.with_name(old.name + '.tmp')
    try:
        with temp.open('w', encoding='utf-8') as stream:
            json.dump({'base_url': base_url, 'model': model, 'api_key': key}, stream, ensure_ascii=False, indent=2)
        if os.name != 'nt':
            temp.chmod(0o600)
        temp.replace(old)
    finally:
        temp.unlink(missing_ok=True)
    return public_settings(project)


def probe_settings(project):
    """Check the declared API's model-list endpoint without sending experiment data."""
    path = settings_path(project)
    if not path.is_file():
        raise ValueError('请先保存API配置。')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        base_url, model = validate_endpoint(data['base_url'], data['model'])
        request = Request(base_url + '/models', headers={
            'Authorization': 'Bearer ' + str(data.get('api_key', ''))})
        with urlopen(request, timeout=10) as response:
            raw = response.read(200001)
        if len(raw) > 200000 or not isinstance(json.loads(raw), dict):
            raise ValueError('invalid response')
        return {'reachable': True, 'model': model, 'endpoint_host': urlsplit(base_url).hostname,
                'note': 'Windows工作站已连接模型列表接口；WSL仿真进程的连通性需通过实际任务验证。'}
    except Exception:
        # Do not return remote response bodies or exception URLs; they may contain secrets.
        raise ValueError('模型列表接口不可用；请检查地址、端口、密钥和服务是否启动。') from None
