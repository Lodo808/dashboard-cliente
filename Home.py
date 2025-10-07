import os
import streamlit as st
import pandas as pd
from db_cliente import engine
import bcrypt

# --- Configurazione pagina ---
st.set_page_config(page_title="Login Dashboard", layout="centered")

# --- Nasconde completamente la sidebar ---
st.markdown("""
    <style>
        [data-testid="stSidebar"], [data-testid="stSidebarNav"], section[data-testid="stSidebarHeader"] {
            display: none !important;
        }
        .block-container {
            max-width: 450px !important;
            margin: auto !important;
            padding-top: 4rem !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- UI login ---
st.title("🔐 Accesso alla Dashboard")

username = st.text_input("Username")
password = st.text_input("Password", type="password")

if st.button("Accedi"):
    if not username or not password:
        st.warning("Inserisci username e password.")
    else:
        try:
            # Cerco utente nel DB
            with engine.connect() as conn:
                query = "SELECT * FROM utenti WHERE username = %(username)s"
                user = pd.read_sql(query, conn, params={"username": username})

            if user.empty:
                st.error("❌ Utente non trovato.")
            else:
                user_data = user.iloc[0]
                stored_pw = user_data["password"]

                try:
                    valid = bcrypt.checkpw(password.encode("utf-8"), stored_pw.encode("utf-8"))
                except:
                    valid = password == stored_pw

                if valid:
                    st.success(f"✅ Benvenuto {user_data['nome_azienda']}!")

                    # Salvo sessione
                    st.session_state["user"] = {
                        "username": user_data["username"],
                        "azienda": user_data["nome_azienda"],
                        "table_name": user_data["nome_azienda"].lower()
                    }
                    st.switch_page("pages/dashboard.py")
                else:
                    st.error("❌ Password errata.")
        except Exception as e:
            st.error(f"Errore connessione DB: {e}")
