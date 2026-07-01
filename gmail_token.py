"""Paso 2: genera token.json con el codigo de autorizacion"""
import sys, json, os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"]
CLIENT_PATH = os.path.join(os.path.dirname(__file__), "client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_PATH, SCOPES, redirect_uri="urn:ietf:wg:oauth:2.0:oob")
code = sys.argv[1]
flow.fetch_token(code=code)
creds = flow.credentials

with open("token.json", "w") as f:
    f.write(creds.to_json())

print("token.json generado correctamente")
