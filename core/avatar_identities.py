"""Resolve avatar assignments against the same local identities as Nexus."""
from pathlib import Path

def targets(repo, rooms=()):
    from shell.local_identity import local_user_directory
    result={}
    personas=Path(repo)/'personas'
    if personas.is_dir():
        for p in personas.iterdir():
            if p.is_dir() and (p/'roster.yaml').exists():
                result[p.name.casefold()]={'id':p.name,'name':p.name,'kind':'persona'}
    for uid,account in local_user_directory(str(repo)).items():
        if uid.casefold() in result:
            continue  # Nexus itself requires unambiguous member identifiers.
        result[uid.casefold()]={'id':uid,'name':account.get('display_name') or uid,'kind':'user'}
    aliases=member_keys(repo)
    for room in rooms:
        for name in room.members:
            key=aliases.get(str(name).casefold(),str(name).casefold())
            result.setdefault(key,{'id':str(name),'name':str(name),'kind':'member'})
    return sorted(result.values(),key=lambda t:(t['kind'],t['name'].casefold()))

def member_keys(repo):
    from shell.local_identity import local_user_directory
    aliases={};ambiguous=set()
    personas=Path(repo)/'personas'
    reserved={p.name.casefold() for p in personas.iterdir() if p.is_dir() and (p/'roster.yaml').exists()} if personas.is_dir() else set()
    for uid,account in local_user_directory(str(repo)).items():
        key=uid.casefold()
        for alias in [uid,account.get('display_name'),account.get('username')]:
            if not alias:continue
            alias=str(alias).casefold()
            if alias in reserved:continue
            if alias in aliases and aliases[alias]!=key:ambiguous.add(alias)
            aliases[alias]=key
    for alias in ambiguous:aliases.pop(alias,None)
    return aliases
