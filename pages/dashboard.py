import os
import json
import math
import streamlit as st
import pandas as pd
import plotly.express as px
import sqlalchemy
from db_cliente import engine
from PIL import Image
from openai import OpenAI
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
st.set_page_config(page_title="Dashboard Azienda", layout="wide")

if "user" not in st.session_state:
    st.switch_page("Home.py")

st.markdown("""
    <style>
        [data-testid="stSidebar"], [data-testid="stSidebarNav"], section[data-testid="stSidebarHeader"] {
            display: none !important;
        }
        .block-container {
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            max-width: 100% !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- Funzione caricamento dati ---
def load_data_from_db(table_name: str):
    try:
        return pd.read_sql(f"SELECT * FROM {table_name}", engine)
    except sqlalchemy.exc.ProgrammingError as e:
        if "doesn't exist" in str(e) or "does not exist" in str(e):
            st.error(f"❌ La tabella '{table_name}' non esiste nel database.")
            return pd.DataFrame()
        else:
            st.error(f"Errore durante la lettura dal database: {e}")
            return pd.DataFrame()

# --- Controllo login ---
if "user" not in st.session_state:
    st.warning("⚠️ Devi effettuare il login prima di accedere alla dashboard.")
    st.stop()

current_user = st.session_state["user"]
table_name = current_user["table_name"]

# --- Header con logo e titolo ---
logo = Image.open("utils/assets/logo_dashboard.png")
col1, col2 = st.columns([1, 6])
with col1:
    st.image(logo, use_container_width=True)
with col2:
    st.title(f"Dashboard Azienda: {current_user.get('azienda', '')}")

# --- Carico dati ---
data = load_data_from_db(table_name)
if data.empty:
    st.warning("⚠️ Nessun dato disponibile per questa azienda.")
    st.stop()

# --- Normalizzazione colonne ---
# Pos -> lat/lon
if "pos" in data.columns:
    data[["lat", "lon"]] = (
        data["pos"].str.split(",", expand=True).apply(lambda col: col.str.strip())
    ).astype(float)

# Timestamp
if "data_ora" in data.columns:
    data["reading_timestamp"] = pd.to_datetime(data["data_ora"], errors="coerce", dayfirst=True)
    data["reading_timestamp_str"] = data["reading_timestamp"].dt.strftime("%d/%m/%Y %H:%M")
else:
    st.error("⚠️ La tabella non contiene la colonna 'data_ora'.")
    st.stop()

# --- FILTRI ---
st.markdown("### 🎚️ Filtri")
col_f1, col_f2 = st.columns(2)
min_date = data["reading_timestamp"].dt.date.min()
max_date = data["reading_timestamp"].dt.date.max()
with col_f1:
    date_range = st.date_input("Periodo", [min_date, max_date])

filtered = data[
    (data["reading_timestamp"].dt.date >= date_range[0]) &
    (data["reading_timestamp"].dt.date <= date_range[1])
]

# --- Stato sessione ---
if "selected_qr" not in st.session_state:
    st.session_state["selected_qr"] = None
if "grid_seed" not in st.session_state:
    st.session_state["grid_seed"] = 0
if "suppress_next_selection" not in st.session_state:
    st.session_state["suppress_next_selection"] = False

# --- KPI ---
st.subheader("📊 KPI principali")

if not filtered.empty:

    # Calcolo indice di freschezza
    def calcola_freschezza(temp_misurata, temp_ideale):
        if pd.isna(temp_misurata) or pd.isna(temp_ideale):
            return 0
        delta = abs(temp_misurata - temp_ideale)
        if delta <= 1:
            return 100
        elif delta <= 3:
            return 80
        elif delta <= 5:
            return 50
        else:
            return 20

    filtered["indice_freschezza"] = filtered.apply(
        lambda r: calcola_freschezza(r["temp_misurata"], r["temp_ideale"]), axis=1
    )

    # KPI
    totale_scansioni = len(filtered)
    freschezza_media = filtered["indice_freschezza"].mean()

    col1, col2 = st.columns(2)
    col1.metric("📦 Totale scansioni", totale_scansioni)
    col2.metric("🥦 Freschezza media", f"{freschezza_media:.1f} / 100")

    # Tabella freschezza per alimento
    if "qr_code" in filtered.columns:
        freschezza_per_alimento = (
            filtered.groupby("qr_code")["indice_freschezza"].mean().reset_index()
        )
        freschezza_per_alimento.columns = ["QR Code", "Indice di freschezza medio"]

        def colore_testo(val):
            if val >= 90:
                color = "#2E7D32"
            elif val >= 70:
                color = "#7CB342"
            elif val >= 50:
                color = "#F9A825"
            elif val >= 30:
                color = "#EF6C00"
            else:
                color = "#C62828"
            return f"color: {color}; font-weight: 600; text-align: center;"

        styled_table = freschezza_per_alimento.style.map(
            colore_testo, subset=["Indice di freschezza medio"]
        ).set_properties(**{
            'text-align': 'center',
            'vertical-align': 'middle'
        })
        st.markdown("### 🥬 Indice di freschezza per QR")
        st.dataframe(styled_table, use_container_width=True)
else:
    st.info("Nessun dato disponibile per i KPI nel periodo selezionato.")

# --- Elenco scansioni ---
st.subheader("📋 Elenco scansioni")

alert_df = filtered.sort_values("reading_timestamp", ascending=False)

if alert_df.empty:
    st.success("✅ Nessun dato disponibile.")
else:
    alert_view = alert_df[["id", "qr_code", "barcode", "prov", "temp_ideale", "temp_misurata", "pos", "reading_timestamp"]]

    gb = GridOptionsBuilder.from_dataframe(alert_view)
    gb.configure_column("id", header_name="ID", width=80, pinned="left")
    gb.configure_selection("single", use_checkbox=False)

    # ✅ Abilita paginazione classica
    gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=20)

    # ✅ Layout auto + nessuno spazio bianco
    gb.configure_grid_options(domLayout="normal", suppressHorizontalScroll=True)

    grid_options = gb.build()

    # ✅ Forza visualizzazione del selettore “Page Size”
    grid_options["pagination"] = True
    grid_options["paginationPageSize"] = 20
    grid_options["paginationPageSizeSelector"] = [10, 20, 50, 100]

    grid_response = AgGrid(
        alert_view,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        height=500,  # 🔹 più spazio visibile, include la barra di paginazione
        theme="streamlit",
        key=f"alert_grid_{st.session_state['grid_seed']}",
        fit_columns_on_grid_load=True,
        use_container_width=True
    )

    selected_rows = grid_response.get("selected_rows", [])
    if isinstance(selected_rows, pd.DataFrame):
        selected_rows = selected_rows.to_dict(orient="records")

    if isinstance(selected_rows, list) and len(selected_rows) > 0:
        sel_qr = selected_rows[0].get("qr_code")
        if sel_qr and sel_qr != st.session_state.get("selected_qr"):
            st.session_state["selected_qr"] = sel_qr
            st.rerun()

    selected_qr = st.session_state.get("selected_qr")
    if selected_qr:
        qr_history = data[data["qr_code"] == selected_qr].sort_values("reading_timestamp")

        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(f"### 📜 Storico QR `{selected_qr}`")
        with c2:
            if st.button("🔁 Reset filtro"):
                st.session_state["selected_qr"] = None
                st.session_state["grid_seed"] += 1
                st.session_state["suppress_next_selection"] = True
                st.rerun()

        st.dataframe(
            qr_history[["id", "reading_timestamp", "prov", "temp_ideale", "temp_misurata", "pos"]],
            use_container_width=True
        )

st.markdown("---")

# --- Mappa scansioni ---
st.subheader("🗺️ Mappa scansioni")

if st.session_state.get("selected_qr"):
    map_data = data[data["qr_code"] == st.session_state["selected_qr"]]
    st.info(f"Mostrando le posizioni delle scansioni per QR: **{st.session_state['selected_qr']}**")
    map_zoom = 6
else:
    map_data = filtered
    map_zoom = 4

if "lat" in map_data.columns and "lon" in map_data.columns and not map_data.empty:
    if "indice_freschezza" not in map_data.columns:
        map_data["indice_freschezza"] = map_data.apply(
            lambda r: abs(r["temp_ideale"] - r["temp_misurata"]) if "temp_ideale" in map_data.columns else 0,
            axis=1
        )

    fig_map = px.scatter_mapbox(
        map_data,
        lat="lat",
        lon="lon",
        color="indice_freschezza",
        hover_data=["qr_code", "barcode", "temp_ideale", "temp_misurata", "indice_freschezza", "prov"],
        color_continuous_scale=[
            (0.0, "#C62828"),
            (0.3, "#EF6C00"),
            (0.6, "#F9A825"),
            (0.8, "#7CB342"),
            (1.0, "#2E7D32")
        ],
        mapbox_style="open-street-map",
        zoom=map_zoom,
        height=550
    )

    fig_map.update_traces(marker=dict(size=15, opacity=0.85))
    fig_map.update_layout(
        legend=dict(
            title="Indice di freschezza",
            yanchor="bottom", y=0.01, xanchor="left", x=0.01
        ),
        margin=dict(l=0, r=0, t=30, b=0)
    )
    config = {
        "scrollZoom": True,
        "displayModeBar": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d", "zoomIn2d", "zoomOut2d"]
    }
    st.plotly_chart(fig_map, use_container_width=True, config=config)
else:
    st.info("ℹ️ Nessuna posizione disponibile per i dati selezionati.")

# --- Snapshot per chatbot ---
def snapshot_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    return {
        "totale_record": int(len(df)),
        "freschezza_media": round(df["indice_freschezza"].mean(), 1) if "indice_freschezza" in df else None,
        "periodo": f"{df['reading_timestamp'].min()} → {df['reading_timestamp'].max()}",
    }

# --- Chatbot AI ---
st.markdown("---")
with st.expander("🤖 Chatbot AI per la Dashboard", expanded=False):
    st.header("Chat")

    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {"role": "system", "content": "Sei un assistente che aiuta a interpretare i dati della dashboard aziendale."}
        ]

    for msg in st.session_state["messages"]:
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        elif msg["role"] == "assistant":
            st.chat_message("assistant").write(msg["content"])

    if user_input := st.chat_input("Chiedi qualcosa sui dati filtrati..."):
        st.session_state["messages"].append({"role": "user", "content": user_input})

        sample_df = filtered.head(10).copy()
        for col in sample_df.columns:
            if pd.api.types.is_datetime64_any_dtype(sample_df[col]):
                sample_df[col] = sample_df[col].astype(str)

        context = {
            "stats": snapshot_stats(filtered),
            "sample_rows": sample_df.to_dict(orient="records")
        }

        prompt = (
            f"Ecco un contesto con i dati filtrati della dashboard:\n\n"
            f"Statistiche: {json.dumps(context['stats'], ensure_ascii=False)}\n\n"
            f"Esempio dati: {json.dumps(context['sample_rows'], ensure_ascii=False)[:2000]}\n\n"
            f"Domanda: {user_input}"
        )

        with st.spinner("Elaborazione risposta..."):
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=st.session_state["messages"] + [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500
            )
            answer = response.choices[0].message.content.strip()

        st.chat_message("assistant").write(answer)
        st.session_state["messages"].append({"role": "assistant", "content": answer})
