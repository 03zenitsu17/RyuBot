"""Paso 1: genera URL de autorizacion Gmail"""
import json, os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"]
CLIENT_PATH = os.path.join(os.path.dirname(__file__), "client_secret.json")

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_PATH, SCOPES, redirect_uri="urn:ietf:wg:oauth:2.0:oob")
auth_url, _ = flow.authorization_url(prompt="consent")

print("ABRE ESTE ENLACE EN TU NAVEGADOR:")
print(auth_url)
print("\nDespues de autorizar, Google te dara un codigo.")
print("COPIALO y ejecuta: python gmail_token.py <codigo>")
