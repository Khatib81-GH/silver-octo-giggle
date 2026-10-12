import json
import os
import re
from pathlib import Path

import requests
import yaml

BASE = "https://awardtravelfinder.com"
UA = "ChatGPT-JED-DTW-Research/1.0"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json, text/yaml, */*"})


def safe(resp):
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "content_type": resp.headers.get("content-type"), "text": resp.text[:10000]}

# Public discovery documents.
agent_r = S.get(f"{BASE}/.well-known/agent.json", timeout=45)
openapi_r = S.get(f"{BASE}/.well-known/openapi.yaml", timeout=45)
agent = safe(agent_r)
openapi_text = openapi_r.text
Path("atf_agent.json").write_text(json.dumps(agent, indent=2), encoding="utf-8")
Path("atf_openapi.yaml").write_text(openapi_text, encoding="utf-8")
print("agent", agent_r.status_code, agent_r.headers.get("content-type"), json.dumps(agent)[:3000])
print("openapi", openapi_r.status_code, openapi_r.headers.get("content-type"), openapi_text[:5000])

try:
    schema = yaml.safe_load(openapi_text) if openapi_r.ok else {}
except Exception as e:
    schema = {"parse_error": str(e)}

# Official autonomous-agent registration flow.
reg_r = S.post(f"{BASE}/api/v1/agent/register", json={"agent_name": "ChatGPT-Mohamad-JED-DTW-20261012"}, timeout=45)
reg = safe(reg_r)
Path("atf_registration_redacted.json").write_text(json.dumps(reg, indent=2), encoding="utf-8")
print("register", reg_r.status_code, json.dumps(reg)[:3000])

# Locate API key in a schema-agnostic way.
def find_key(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = k.lower().replace("-", "_")
            if lk in {"api_key", "apikey", "key", "token", "access_token"} and isinstance(v, str) and len(v) >= 12:
                return v
        for v in obj.values():
            got = find_key(v)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = find_key(v)
            if got:
                return got
    return None

api_key = find_key(reg)
if not api_key:
    raise SystemExit("No API key found in registration response")

# Redact persisted registration data.
def redact(obj):
    if isinstance(obj, dict):
        return {k: ("***REDACTED***" if isinstance(v, str) and v == api_key else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj
Path("atf_registration_redacted.json").write_text(json.dumps(redact(reg), indent=2), encoding="utf-8")

# Infer security header from OpenAPI. Try common forms if schema is ambiguous.
security_schemes = (((schema or {}).get("components") or {}).get("securitySchemes") or {}) if isinstance(schema, dict) else {}
print("security schemes", json.dumps(security_schemes)[:3000])
header_candidates = []
for name, spec in security_schemes.items():
    if not isinstance(spec, dict):
        continue
    typ = spec.get("type")
    if typ == "apiKey" and spec.get("in") == "header":
        header_candidates.append({spec.get("name", "X-API-Key"): api_key})
    elif typ in {"http", "oauth2", "openIdConnect"}:
        header_candidates.append({"Authorization": f"Bearer {api_key}"})
header_candidates += [
    {"X-API-Key": api_key},
    {"Authorization": f"Bearer {api_key}"},
    {"Authorization": api_key},
]
# de-duplicate
uniq=[]
for h in header_candidates:
    if h not in uniq: uniq.append(h)
header_candidates=uniq

paths = (schema or {}).get("paths") or {} if isinstance(schema, dict) else {}
summary = []
for path, methods in paths.items():
    if not isinstance(methods, dict):
        continue
    for method, operation in methods.items():
        if method.lower() not in {"get","post","put","patch","delete"} or not isinstance(operation, dict):
            continue
        summary.append({
            "path": path,
            "method": method.upper(),
            "operationId": operation.get("operationId"),
            "summary": operation.get("summary"),
            "parameters": operation.get("parameters"),
            "requestBody": operation.get("requestBody"),
        })
Path("atf_endpoints.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("endpoints", json.dumps(summary)[:10000])

# Find monthly/search operations and build requests from the schema. Prefer monthly to cover a full month in one quota unit.
def resolve(ref):
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return None
    cur=schema
    for token in ref[2:].split("/"):
        cur=cur[token.replace("~1","/").replace("~0","~")]
    return cur

def deref(obj):
    if isinstance(obj, dict) and "$ref" in obj:
        return deref(resolve(obj["$ref"]))
    if isinstance(obj, dict): return {k:deref(v) for k,v in obj.items()}
    if isinstance(obj, list): return [deref(v) for v in obj]
    return obj

ops=[]
for path, methods in paths.items():
    for method, operation in (methods or {}).items():
        if method.lower() not in {"get","post"} or not isinstance(operation,dict): continue
        label=f"{operation.get('operationId','')} {operation.get('summary','')} {path}".lower()
        if any(x in label for x in ["monthly", "availability", "search"]):
            ops.append((path,method.upper(),operation,label))
print("candidate ops", [(p,m,o.get('operationId'),o.get('summary')) for p,m,o,_ in ops])

# Value chooser for known field semantics.
def value_for(name, month):
    n=name.lower().replace("-","_")
    vals={
        "origin":"JED","origin_iata":"JED","origin_airport":"JED","from":"JED","departure":"JED",
        "destination":"DTW","destination_iata":"DTW","destination_airport":"DTW","to":"DTW","arrival":"DTW",
        "airline":"KL","airline_code":"KL","carrier":"KL","carrier_code":"KL","program":"flying_blue","program_code":"KL",
        "month":month,"year_month":month,"travel_month":month,
        "date":"2026-12-25","departure_date":"2026-12-25","travel_date":"2026-12-25",
        "cabin":"economy","cabin_class":"economy","class":"economy",
        "adults":1,"passengers":1,"seats":1,"number_of_seats":1,"min_seats":1,
    }
    return vals.get(n)

def build_payload(operation, month):
    query={}; body={}
    for param in operation.get("parameters") or []:
        param=deref(param)
        name=param.get("name")
        loc=param.get("in")
        v=value_for(name,month)
        if v is not None:
            (query if loc=="query" else body)[name]=v
    rb=deref(operation.get("requestBody") or {})
    content=(rb.get("content") or {}) if isinstance(rb,dict) else {}
    js=content.get("application/json") or next(iter(content.values()),{}) if content else {}
    sch=deref((js or {}).get("schema") or {})
    props=sch.get("properties") or {} if isinstance(sch,dict) else {}
    required=sch.get("required") or [] if isinstance(sch,dict) else []
    for name,spec in props.items():
        v=value_for(name,month)
        if v is None and name in required:
            # enum/default/example fallbacks
            if isinstance(spec,dict):
                v=spec.get("example",spec.get("default"))
                if v is None and spec.get("enum"): v=spec["enum"][0]
        if v is not None: body[name]=v
    return query,body

results=[]
# Search December and January using likely monthly endpoint(s), max 3 successful calls due free quota.
for month in ["2026-12","2027-01"]:
    success=False
    for path,method,operation,label in sorted(ops,key=lambda x:("monthly" not in x[3], "availability" not in x[3])):
        query,body=build_payload(operation,month)
        url=path if path.startswith("http") else BASE+path
        for headers in header_candidates:
            try:
                r=S.request(method,url,params=query,json=body if method=="POST" else None,headers=headers,timeout=120)
                data=safe(r)
                attempt={"month":month,"path":path,"method":method,"query":query,"body":body,"auth_header_names":list(headers),"status":r.status_code,"response":data}
                results.append(attempt)
                print("attempt",month,method,path,r.status_code,json.dumps(data)[:5000])
                if r.ok and not (isinstance(data,dict) and data.get("error")):
                    success=True
                    break
            except Exception as e:
                results.append({"month":month,"path":path,"method":method,"query":query,"body":body,"error":str(e)})
        if success: break
    if not success:
        print("No successful ATF search for",month)

# Remove any accidental key echo before persistence.
text=json.dumps(results,indent=2)
text=text.replace(api_key,"***REDACTED***")
Path("atf_results.json").write_text(text,encoding="utf-8")
print("ATF_RESULTS_BEGIN")
print(text[:50000])
print("ATF_RESULTS_END")
