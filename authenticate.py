"""
Run this once to generate your OAuth refresh token.
It will open a browser window asking you to authorize the app.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/adwords"]

flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", scopes=SCOPES)
credentials = flow.run_local_server(port=8080)

print("\n--- COPY THESE VALUES INTO google-ads.yaml ---")
print(f"refresh_token: {credentials.refresh_token}")
print(f"client_id:     {credentials.client_id}")
print(f"client_secret: {credentials.client_secret}")
