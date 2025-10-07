import base64
import json
import sqlalchemy
import streamlit as st
from google.cloud.sql.connector import Connector
from google.oauth2.service_account import Credentials

# 🔹 Legge le credenziali codificate in base64 da Streamlit secrets
creds_b64 = st.secrets["GOOGLE_CREDENTIALS_B64"]
creds_dict = json.loads(base64.b64decode(creds_b64))
credentials = Credentials.from_service_account_info(creds_dict)

PROJECT_ID = st.secrets["PROJECT_ID"]
REGION = st.secrets["REGION"]
INSTANCE_NAME = st.secrets["INSTANCE_NAME"]
DB_USER = st.secrets["DB_USER"]
DB_PASS = st.secrets["DB_PASS"]
DB_NAME = st.secrets["DB_NAME"]

def get_engine():
    connector = Connector(credentials=credentials)

    def getconn():
        conn = connector.connect(
            f"{PROJECT_ID}:{REGION}:{INSTANCE_NAME}",
            "pymysql",
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
        )
        return conn

    return sqlalchemy.create_engine(
        "mysql+pymysql://",
        creator=getconn,
        pool_pre_ping=True,
    )

engine = get_engine()
