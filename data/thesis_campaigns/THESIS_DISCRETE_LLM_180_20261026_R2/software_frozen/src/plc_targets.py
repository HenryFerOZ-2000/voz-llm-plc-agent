"""Normal download targets: persisted configuration is never evidence of connection."""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import tempfile


def normalize_target(candidate: dict) -> dict:
    target=copy.deepcopy(candidate)
    kind=str(target.get('target_type') or 'PLCSIM_ADVANCED').strip().upper()
    if kind not in ('PLCSIM_ADVANCED','PHYSICAL_PLC'):
        raise ValueError('Tipo de destino no compatible.')
    target['target_type']=kind
    for key in ('target_name','configuration_mode','pc_interface','target_interface','instance_name'):
        if key in target:target[key]=str(target[key] or '').strip()
    address=str(target.get('target_address') or '').strip()
    if address:
        try:ip=ipaddress.IPv4Address(address)
        except ipaddress.AddressValueError as error:raise ValueError('Dirección IPv4 no válida.') from error
        if ip.is_unspecified or ip.is_multicast or ip.is_loopback or int(ip)==0xffffffff:
            raise ValueError('Se necesita la dirección unicast del PLC.')
        target['target_address']=str(ip)
    elif 'target_address' in target:target['target_address']=''
    for key in ('pc_interface_number','instance_id'):
        if target.get(key) not in (None,''):
            if isinstance(target[key],bool):raise ValueError('Identificador no válido: '+key)
            try:value=int(target[key])
            except (TypeError,ValueError) as error:raise ValueError('Identificador no válido: '+key) from error
            if value<0:raise ValueError('Identificador no válido: '+key)
            target[key]=value
        else:target.pop(key,None)
    return target


def target_identity(target: dict) -> str:
    normalized=normalize_target(target)
    keys=('target_type','configuration_mode','pc_interface','pc_interface_number','target_interface',
        'target_address','instance_name','instance_id','project_path','plc_name')
    values={key:normalized.get(key) for key in keys}
    if values['project_path']:values['project_path']=os.path.normcase(os.path.abspath(values['project_path']))
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


def read_target_revision(root: Path) -> dict:
    return {name:hashlib.sha256((root/'config'/name).read_bytes()).hexdigest()
        if (root/'config'/name).is_file() else None
        for name in ('tia_openness_config.json','tia_projects.json')}


def load_normal_target(root: Path) -> dict:
    from tia_openness import load_tia_config,resolve_download_target,normal_project_path
    config=load_tia_config(root)
    target=resolve_download_target(config,'normal')
    runtime=config.get('plcsim_runtime') or {}
    if target['target_type']=='PLCSIM_ADVANCED':
        target.setdefault('instance_name',runtime.get('instance_name','TESIS_PLC_SIM'))
        if 'instance_id' in runtime:target.setdefault('instance_id',runtime['instance_id'])
    target['project_path']=normal_project_path(root)
    target['plc_name']=config.get('plc_name','')
    return normalize_target(target)


def save_normal_target(root: Path,target: dict,expected_revision: dict) -> dict:
    from tia_openness import load_tia_config,normal_project_path
    normalized=normalize_target(target)
    if not normalized.get('target_address'):raise ValueError('Indique la dirección del destino seleccionado.')
    if not normalized.get('pc_interface') or not normalized.get('target_interface'):
        raise ValueError('Seleccione la interfaz PG/PC y el puerto del proyecto.')
    if normalized['target_type']=='PLCSIM_ADVANCED' and not normalized.get('instance_name'):
        raise ValueError('Seleccione una instancia virtual inequívoca.')
    if read_target_revision(root)!=expected_revision:
        raise ValueError('La configuración cambió; vuelva a abrir el selector.')
    project=normal_project_path(root)
    if normalized.get('project_path') and os.path.normcase(os.path.abspath(normalized['project_path']))!=os.path.normcase(os.path.abspath(project)):
        raise ValueError('El proyecto Normal cambió; vuelva a abrir el selector.')
    config=copy.deepcopy(load_tia_config(root))
    stored={key:value for key,value in normalized.items() if key not in ('project_path','plc_name')}
    config.setdefault('download_targets',{})['normal']=stored
    path=root/'config/tia_openness_config.json';path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as handle:
            temporary=Path(handle.name)
            json.dump(config,handle,ensure_ascii=False,indent=2)
            handle.flush();os.fsync(handle.fileno())
        if read_target_revision(root)!=expected_revision:
            raise ValueError('La configuración cambió; no se guardó el destino.')
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return load_normal_target(root)
