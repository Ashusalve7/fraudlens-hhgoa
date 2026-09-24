# TigerGraph credential rotation

Use this procedure whenever a TigerGraph credential has appeared in source, logs, chat, video, a shared archive, or an untrusted machine.

## 1. Create a dedicated runtime identity

Prefer a dedicated TigerGraph user with only the permissions FraudLens needs. Create a new secret for that user from the TigerGraph/Savanna administration surface. Do not reuse the cloud-console administrator password.

## 2. Update the local ignored environment file

```dotenv
TG_HOST=https://<workspace-host>
TG_SECRET=<new-dedicated-secret>
TG_GRAPHNAME=FraudGraph
```

`.env` is ignored and must never be committed or included in a submission archive.

## 3. Verify the new credential

From a clean Python process:

```python
from dotenv import load_dotenv
import os
import pyTigerGraph as tg

load_dotenv("fraudlens/.env")
conn = tg.TigerGraphConnection(
    host=os.environ["TG_HOST"].rstrip("/"),
    graphname=os.environ.get("TG_GRAPHNAME", "FraudGraph"),
    gsqlSecret=os.environ["TG_SECRET"],
)
assert conn.echo()
```

## 4. Revoke the exposed secret

- Drop the old secret alias through TigerGraph credential management.
- If the old value is also a cloud workspace/static secret, rotate it in the Savanna workspace administration page. Dropping a database alias alone may not replace a cloud-console credential.
- Verify the old value is rejected from a new process and new machine.

## 5. Clean distributed material

- Remove the credential from source and notebooks.
- Purge it from Git history if the repository was ever committed or shared.
- Rotate again if it appeared in a recording, issue, log, or archive that cannot be replaced.
- Run `scripts/secret_scan.py` and the CI secret scan.

## 6. Record completion without recording the secret

Record only:

- rotation date;
- old alias name;
- new alias/user name;
- verification result;
- incident reference, if applicable.

Never record the secret value or a screenshot that exposes it.
