import os
import json
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

if "user" not in st.session_state:
    st.warning("⚠️ Devi effettuare il login prima di accedere alla dashboard.")
    st.stop()
current_user = st.session_state["user"]
table_name = current_user["table_name"]

logo = Image.open("utils/assets/logo_dashboard.png")
col1, col2 = st.columns([1, 6])
with col1:
    st.image(logo, use_container_width=True)
with col2:
    st.title(f"Dashboard Azienda: {current_user.get('azienda', '')}")

# Carico i dati
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
    data["reading_timestamp"] = pd.to_datetime(data["data_ora"], errors="coerce")
else:
    st.error("⚠️ La tabella non contiene la colonna 'data_ora'.")
    st.stop()

# In-range / Out-of-range
if "temp_ideale" in data.columns and "temp_misurata" in data.columns:
    data["in_range"] = (abs(data["temp_misurata"] - data["temp_ideale"]) <= 1.0)
    data["out_of_range"] = ~data["in_range"]
else:
    data["in_range"] = True
    data["out_of_range"] = False

# --- FILTRI ---
st.sidebar.header("Filtri")
min_date = data["reading_timestamp"].dt.date.min()
max_date = data["reading_timestamp"].dt.date.max()
date_range = st.sidebar.date_input("Periodo", [min_date, max_date])

filtered = data[
    (data["reading_timestamp"].dt.date >= date_range[0]) &
    (data["reading_timestamp"].dt.date <= date_range[1])
]

if "selected_qr" not in st.session_state:
    st.session_state["selected_qr"] = None
if "grid_seed" not in st.session_state:  # forza ricreazione del componente AgGrid
    st.session_state["grid_seed"] = 0
if "suppress_next_selection" not in st.session_state:
    st.session_state["suppress_next_selection"] = False

# --- KPI ---
st.subheader("📌 KPI principali")
col1, col2, col3 = st.columns(3)
col1.metric("Totale scansioni", len(filtered))
col2.metric("In range", int(filtered["in_range"].sum()))
col3.metric("Fuori range", int(filtered["out_of_range"].sum()))

# --- Alert Center ---
st.subheader("🚨 Alert Center")

alert_df = filtered[filtered["out_of_range"]].sort_values("reading_timestamp", ascending=False)

if alert_df.empty:
    st.success("✅ Nessun allarme.")
else:
    st.markdown("Clicca su una riga per vedere lo storico di un QR specifico.")

    alert_view = alert_df[["qr_code","barcode","prov","temp_ideale","temp_misurata","pos","reading_timestamp"]]

    gb = GridOptionsBuilder.from_dataframe(alert_view)
    gb.configure_selection("single", use_checkbox=False)
    gb.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=20)
    gb.configure_grid_options(domLayout="normal", rowHeight=30)
    grid_options = gb.build()

    # ⚠️ Chiave con seed per forzare un componente "nuovo" dopo il reset
    grid_response = AgGrid(
        alert_view,
        gridOptions=grid_options,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        height=380,
        theme="streamlit",
        key=f"alert_grid_{st.session_state['grid_seed']}",
    )

    # Se devo ignorare la prima selezione dopo un reset, consumala e non fare nulla
    if st.session_state.get("suppress_next_selection", False):
        st.session_state["suppress_next_selection"] = False
        selected_rows = []
    else:
        selected_rows = grid_response.get("selected_rows", [])
        if isinstance(selected_rows, pd.DataFrame):
            selected_rows = selected_rows.to_dict(orient="records")

    # Aggiorna la selezione solo se c'è una riga davvero nuova
    if isinstance(selected_rows, list) and len(selected_rows) > 0:
        sel_qr = selected_rows[0].get("qr_code")
        if sel_qr and sel_qr != st.session_state.get("selected_qr"):
            st.session_state["selected_qr"] = sel_qr
            st.rerun()

    # --- Storico QR + bottone Reset vicino al titolo ---
    selected_qr = st.session_state.get("selected_qr")
    if selected_qr:
        qr_history = data[data["qr_code"] == selected_qr].sort_values("reading_timestamp")

        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(f"### 📜 Storico QR `{selected_qr}`")
        with c2:
            if st.button("🔁 Reset filtro"):
                # 1) azzera selezione
                st.session_state["selected_qr"] = None
                # 2) incrementa seed per ricreare il componente AgGrid pulito (senza selezione)
                st.session_state["grid_seed"] += 1
                # 3) ignora la prima selezione che AgGrid potrebbe riproporre
                st.session_state["suppress_next_selection"] = True
                st.rerun()

        st.dataframe(
            qr_history[["reading_timestamp","prov","temp_ideale","temp_misurata","pos"]],
            use_container_width=True
        )

        fig_qr = px.line(
            qr_history,
            x="reading_timestamp",
            y=["temp_ideale","temp_misurata"],
            markers=True,
            labels={"value":"Temperatura (°C)","variable":"Tipo"},
            title=f"Andamento temperature - QR {selected_qr}"
        )
        st.plotly_chart(fig_qr, use_container_width=True)

# --- Mappa ---
st.subheader("🗺️ Mappa scansioni")

# Selezione dataset in base allo stato
if st.session_state.get("selected_qr"):
    map_data = data[data["qr_code"] == st.session_state["selected_qr"]]
    st.info(f"Mostrando le posizioni delle scansioni per QR: **{st.session_state['selected_qr']}**")
    map_zoom = 6
else:
    map_data = filtered
    map_zoom = 4

# Mostra mappa
if "lat" in map_data.columns and "lon" in map_data.columns and not map_data.empty:
    fig_map = px.scatter_mapbox(
        map_data,
        lat="lat",
        lon="lon",
        color="out_of_range",
        hover_data=["qr_code", "barcode", "temp_ideale", "temp_misurata", "prov"],
        mapbox_style="open-street-map",
        zoom=map_zoom,
        height=500
    )
    fig_map.update_layout(
        legend=dict(yanchor="bottom", y=0.01, xanchor="left", x=0.01),
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

# --- Trend Temperature ---
st.subheader("📈 Andamento temperature")
if not filtered.empty:
    fig_trend = px.line(
        filtered,
        x="reading_timestamp",
        y=["temp_ideale", "temp_misurata"],
        labels={"value": "Temperatura (°C)", "variable": "Tipo"},
        markers=True
    )
    st.plotly_chart(fig_trend, use_container_width=True)
else:
    st.info("ℹ️ Nessun dato disponibile per il periodo selezionato.")

# --- Funzione riassuntiva per il contesto
def snapshot_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    return {
        "totale_record": int(len(df)),
        "in_range_pct": round(df["in_range"].mean() * 100, 1) if "in_range" in df else None,
        "out_of_range_pct": round(df["out_of_range"].mean() * 100, 1) if "out_of_range" in df else None,
        "periodo": f"{df['reading_timestamp'].min()} → {df['reading_timestamp'].max()}",
    }

# --- Chatbot UI
st.markdown("---")

with st.expander("🤖 Chatbot AI per la Dashboard", expanded=False):
    st.header("Chat")

    # Mantieni storico chat
    if "messages" not in st.session_state:
        st.session_state["messages"] = [
            {"role": "system", "content": "Sei un assistente che aiuta a interpretare i dati della dashboard aziendale."}
        ]

    # Mostra i messaggi precedenti
    for msg in st.session_state["messages"]:
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        elif msg["role"] == "assistant":
            st.chat_message("assistant").write(msg["content"])

    # Input utente
    if user_input := st.chat_input("Chiedi qualcosa sui dati filtrati..."):
        # Aggiungi domanda utente
        st.session_state["messages"].append({"role": "user", "content": user_input})

        # Prepara dati di contesto per il modello
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

        # Mostra e salva risposta
        st.chat_message("assistant").write(answer)
        st.session_state["messages"].append({"role": "assistant", "content": answer})