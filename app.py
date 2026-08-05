from datetime import datetime
import hashlib
import os
import pandas as pd
import requests
import streamlit as st
from fpdf import FPDF
import psycopg2
from psycopg2 import IntegrityError

# ==========================================
# 1. DATABASE CLOUD (POSTGRESQL) & AUTENTICAZIONE
# ==========================================
def get_db_connection():
    # Streamlit leggerà l'URL del database dai "Secrets" (variabili segrete)
    return psycopg2.connect(st.secrets["DB_URL"])

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS utenti (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cronologia (
            id SERIAL PRIMARY KEY,
            user_id INTEGER DEFAULT 1,
            data TEXT,
            azione TEXT,
            cliente TEXT,
            dettaglio TEXT,
            importo TEXT
        )
    """)

    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def registra_utente(username, password):
    init_db()
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO utenti (username, password_hash) VALUES (%s, %s)",
            (username.strip().lower(), hash_password(password)),
        )
        conn.commit()
        conn.close()
        return True, "Account creato con successo! Ora puoi accedere."
    except IntegrityError:
        conn.close()
        return False, "Nome utente già esistente. Scegli un altro nome."

def verifica_login(username, password):
    user_clean = username.strip().lower()
    
    # Account Master
    if user_clean == "admin" and password == "admin":
        return (999, "Amministratore")
    
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, username FROM utenti WHERE username = %s AND password_hash = %s",
        (user_clean, hash_password(password)),
    )
    user = cursor.fetchone()
    conn.close()
    return user  

def carica_cronologia(user_id):
    init_db()
    conn = get_db_connection()
    df = pd.read_sql_query(
        """
        SELECT data as Data, azione as Azione, cliente as Cliente, dettaglio as Dettaglio, importo as Importo 
        FROM cronologia 
        WHERE user_id = %s 
        ORDER BY id DESC
    """,
        conn,
        params=(user_id,),
    )
    conn.close()
    return df

def salva_cronologia(user_id, azione, cliente, dettaglio, importo="-"):
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO cronologia (user_id, data, azione, cliente, dettaglio, importo)
        VALUES (%s, %s, %s, %s, %s, %s)
    """,
        (
            user_id,
            datetime.now().strftime("%d/%m/%Y %H:%M"),
            azione,
            cliente,
            dettaglio,
            importo,
        ),
    )
    conn.commit()
    conn.close()

def pulisci(testo):
    if testo is None:
        return ""
    testo = str(testo).replace("€", "EUR").replace("°", " deg.")
    sostituzioni = {
        "à": "a'", "è": "e'", "é": "e'", "ì": "i'", "ò": "o'", "ù": "u'",
        "À": "A'", "È": "E'", "Ì": "I'", "Ò": "O'", "Ù": "U'",
    }
    for orig, sost in sostituzioni.items():
        testo = testo.replace(orig, sost)
    return testo.encode("latin-1", "replace").decode("latin-1")

# ==========================================
# 2. API DISTANZE E PEDAGGI
# ==========================================
def calcola_distanza_api(partenza, arrivo, moltiplicatore_pedaggio=0.18):
    headers = {"User-Agent": "TruckApp/1.0 (contact: info@truckapp.local)"}
    try:
        res_p = requests.get(
            f"https://nominatim.openstreetmap.org/search?q={partenza}&format=json&limit=1",
            headers=headers,
            timeout=5,
        ).json()
        res_a = requests.get(
            f"https://nominatim.openstreetmap.org/search?q={arrivo}&format=json&limit=1",
            headers=headers,
            timeout=5,
        ).json()

        if res_p and res_a:
            lat1, lon1 = res_p[0]["lat"], res_p[0]["lon"]
            lat2, lon2 = res_a[0]["lat"], res_a[0]["lon"]
            url_route = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
            res_route = requests.get(url_route, timeout=5).json()

            if "routes" in res_route and len(res_route["routes"]) > 0:
                km = round(res_route["routes"][0]["distance"] / 1000.0, 1)
                pedaggio = round((km * 0.80) * moltiplicatore_pedaggio, 2)
                return km, pedaggio
    except Exception:
        return None, None
    return None, None

# ==========================================
# 3. GENERAZIONE PDF BOLLA CMR
# ==========================================
class MioPDF(FPDF):
    def disegna_cella_sezione(self, x, y, w, h, titolo, valore="", bg_hdr=True):
        self.set_line_width(0.3)
        self.set_draw_color(60, 60, 60)
        self.rect(x, y, w, h)
        if bg_hdr:
            self.set_fill_color(240, 242, 245)
            self.rect(x, y, w, 5, "F")
            self.line(x, y + 5, x + w, y + 5)
        self.set_xy(x + 1.5, y + 0.8)
        self.set_font("Helvetica", "B", 6.5)
        self.set_text_color(50, 50, 50)
        self.cell(w - 3, 3.5, pulisci(titolo.upper()), ln=0)
        if valore:
            self.set_xy(x + 2, y + 5.5)
            self.set_font("Helvetica", "B", 8.5)
            self.set_text_color(0, 0, 0)
            self.multi_cell(w - 4, 3.8, pulisci(valore), border=0, align="L")
            
    def disegna_firma_orari(self, x, y, w, h, titolo):
        self.rect(x, y, w, h)
        self.set_xy(x, y + 2)
        self.set_font("Helvetica", "B", 7)
        self.cell(w, 3, pulisci(titolo), align="C", ln=1)
        y_grid = y + h - 8
        self.set_draw_color(60, 60, 60)
        self.line(x, y_grid, x + w, y_grid) 
        self.line(x + (w/2), y_grid, x + (w/2), y + h) 
        self.set_font("Helvetica", "I", 6.5)
        self.set_text_color(100, 100, 100)
        self.set_xy(x, y_grid + 0.5)
        self.cell(w/2, 3, "Ora Arrivo:", align="C")
        self.set_xy(x + (w/2), y_grid + 0.5)
        self.cell(w/2, 3, "Ora Part.:", align="C")
        self.set_text_color(0, 0, 0)

def crea_pdf_bolla(dati, logo_path=None):
    pdf = MioPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    pdf.set_auto_page_break(False)

    pdf.set_fill_color(26, 82, 118)
    pdf.rect(10, 10, 190, 18, "F")
    offset_x = 12
    w_title = 100
    
    if logo_path and os.path.exists(logo_path):
        try:
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(10, 10, 45, 18, "F")
            pdf.set_draw_color(26, 82, 118)
            pdf.rect(10, 10, 45, 18) 
            pdf.image(logo_path, 12, 11, h=16)
            offset_x = 58
            w_title = 54
        except Exception:
            pass

    pdf.set_xy(offset_x, 11)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(w_title, 5, pulisci(dati["vettore"]), ln=0, align="L")
    pdf.set_xy(offset_x, 16.5)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.cell(w_title, 4, pulisci(dati.get("dati_azienda", "")), ln=0, align="L")
    pdf.set_xy(offset_x, 22)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(w_title, 4, "DOCUMENTO DI TRASPORTO MERCI SU STRADA", ln=0, align="L")

    pdf.set_xy(110, 12)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(88, 6, "LETTERA DI VETTURA / BOLLA", ln=1, align="R")
    pdf.set_xy(110, 20)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(88, 5, pulisci(f"N. {dati['num_doc']}  |  Data: {dati['data']}"), ln=1, align="R")

    pdf.disegna_cella_sezione(10, 30, 45, 12, "Data e Ora Ritiro", f"{dati['data']} - {dati['ora']}")
    pdf.disegna_cella_sezione(55, 30, 45, 12, "Riferimento Doc.", dati.get("rif", "N/A"))
    pdf.disegna_cella_sezione(100, 30, 45, 12, "Compagnia Navale", dati.get("compagnia", "N/A"))
    pdf.disegna_cella_sezione(145, 30, 55, 12, "Booking / Riferimento", dati.get("booking", "N/A"))
    pdf.disegna_cella_sezione(10, 43, 93, 20, "1. Committente / Mittente", dati["committente"])
    pdf.disegna_cella_sezione(103, 43, 97, 20, "2. Vettore / Trasportatore", dati["vettore"])

    pdf.disegna_cella_sezione(10, 64, 93, 12, "3.1 Luogo di Carico / Terminal Ritiro 1", dati.get("r1", ""))
    pdf.disegna_cella_sezione(10, 76, 93, 12, "3.2 Luogo di Carico 2", dati.get("r2", ""))
    pdf.disegna_cella_sezione(10, 88, 93, 12, "3.3 Luogo di Carico 3", dati.get("r3", ""))

    info_mezzo = f"Autista: {dati['autista']}\n\nTrattore: {dati['trattore']}\nRimorchio: {dati['rimorchio']}"
    pdf.disegna_cella_sezione(103, 64, 97, 36, "4. Conducente & Automezzo", info_mezzo)

    pdf.disegna_cella_sezione(10, 101, 93, 12, "5.1 Luogo di Consegna / Scarico 1", dati.get("s1", ""))
    pdf.disegna_cella_sezione(10, 113, 93, 12, "5.2 Luogo di Consegna 2", dati.get("s2", ""))
    pdf.disegna_cella_sezione(10, 125, 93, 12, "5.3 Luogo di Consegna 3", dati.get("s3", ""))

    info_cnt = f"Sigla/N deg. Container: {dati['container']}\n\nPeso Lordo (Kg): {dati['peso']}"
    pdf.disegna_cella_sezione(103, 101, 97, 36, "6. Identificativo Container & Peso", info_cnt)

    pdf.disegna_cella_sezione(10, 138, 190, 18, "7. Natura della Merce e Tipologia Imballo", dati["merce"])
    pdf.disegna_cella_sezione(10, 157, 190, 18, "8. Note operative / Riserve del Vettore all'Atto del Carico", dati["note"])

    pdf.set_fill_color(245, 245, 245)
    pdf.rect(10, 176, 190, 61)
    pdf.set_line_width(0.3)
    pdf.set_draw_color(60, 60, 60)
    pdf.rect(10, 176, 190, 61)

    pdf.set_xy(13, 178)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(26, 82, 118)
    pdf.cell(184, 4, pulisci("DIRETTIVE, ISTRUZIONI DI TRASPORTO E CONDIZIONI GENERALI"), ln=1)
    pdf.line(13, 183, 197, 183)

    pdf.set_font("Helvetica", "", 6.8)
    pdf.set_text_color(40, 40, 40)
    direttive_testo = (
        "1. NORMATIVA APPLICABILE: Il presente trasporto e' regolato dalle norme del Codice Civile italiano (Art. 1696 e succ.) "
        "e, per i trasporti internazionali, dalla Convenzione relativo al contratto di trasporto internazionale di merci su strada (CMR).\n"
        "2. ISTRUZIONI DI SICUREZZA: Il conducente e' tenuto a verificare l'integrita' dei sigilli e la corrispondenza dei contrassegni.\n"
        "3. SOSTE E PERCORSI: Il trasporto deve avvenire nel rispetto dei tempi di guida e di riposo (Regolamento CE 561/2006).\n"
        "4. RESA E CONSEGNA: La merce viaggia a rischio del committente salvo i casi di responsabilita' imputabile al vettore ai sensi di legge."
    )
    pdf.set_xy(13, 185)
    pdf.multi_cell(184, 3.2, pulisci(direttive_testo), border=0, align="J")

    pdf.set_xy(13, 213)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(184, 4, pulisci("PRESCRIZIONI PARTICOLARI DEL COMMITTENTE / ISTRUZIONI:"), ln=1)

    pdf.set_font("Helvetica", "I", 7)
    pdf.set_xy(13, 218)
    istruzioni_extra = dati.get("note_committente") if dati.get("note_committente") else "Nessuna istruzione particolare specificata."
    pdf.multi_cell(184, 3.2, pulisci(istruzioni_extra), border=0, align="L")

    h_firme, y_firme = 38, 238
    pdf.disegna_firma_orari(10, y_firme, 60, h_firme, "Firma Mittente / Caricatore")
    pdf.disegna_firma_orari(75, y_firme, 60, h_firme, "Firma Vettore / Conducente")
    pdf.disegna_firma_orari(140, y_firme, 60, h_firme, "Firma Destinatario")

    out = pdf.output(dest="S")
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")

# ==========================================
# 4. GENERAZIONE PDF PREVENTIVO (INVARIATO)
# ==========================================
def crea_pdf_preventivo(dati, logo_path=None):
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_fill_color(26, 82, 118)
    pdf.rect(15, 15, 180, 22, "F")
    offset_x = 20
    
    if logo_path and os.path.exists(logo_path):
        try:
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(15, 15, 45, 22, "F")
            pdf.set_draw_color(26, 82, 118)
            pdf.rect(15, 15, 45, 22)
            pdf.image(logo_path, 17, 17, h=18)
            offset_x = 65
        except Exception:
            pass

    pdf.set_xy(offset_x, 19)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(80, 6, "PREVENTIVO DI TRASPORTO", ln=0)
    pdf.set_xy(120, 19)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(70, 6, f"Data: {datetime.now().strftime('%d/%m/%Y')}", ln=1, align="R")

    pdf.set_xy(15, 43)
    pdf.set_fill_color(248, 249, 250)
    pdf.rect(15, 43, 180, 28, "F")
    pdf.set_draw_color(210, 215, 220)
    pdf.rect(15, 43, 180, 28)
    pdf.set_xy(20, 46)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(26, 82, 118)
    pdf.cell(85, 5, "COMMITTENTE / CLIENTE", ln=0)
    pdf.cell(85, 5, "DETTAGLI ITINERARIO", ln=1)

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(20, 53)
    pdf.cell(85, 5, pulisci(dati["cliente"]), ln=0)
    tipo_v = "Andata e Ritorno" if dati["is_ritorno"] else "Solo Andata"
    pdf.cell(85, 5, pulisci(f"Tratta: {dati['partenza']} -> {dati['arrivo']}"), ln=1)

    pdf.set_xy(15, 78)
    pdf.set_fill_color(26, 82, 118)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(95, 8, pulisci(" DESCRIZIONE SERVIZIO"), border=1, fill=True)
    pdf.cell(45, 8, pulisci("PARAMETRI"), border=1, fill=True, align="C")
    pdf.cell(40, 8, pulisci("IMPORTO (EUR)"), border=1, fill=True, align="R")
    pdf.ln()

    pdf.set_text_color(40, 40, 40)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_x(15)
    pdf.cell(95, 8, pulisci(f" Quota Trasporto ({tipo_v})"), border=1)
    pdf.cell(45, 8, pulisci(f"{dati['km']} Km x {dati['tariffa']:.2f} EUR"), border=1, align="C")
    pdf.cell(40, 8, f"{dati['costo_viaggio']:.2f} EUR", border=1, align="R")
    pdf.ln()

    pdf.set_x(15)
    pdf.cell(95, 8, pulisci(" Stima Pedaggi Autostradali"), border=1)
    pdf.cell(45, 8, pulisci("Calcolo Stimato"), border=1, align="C")
    pdf.cell(40, 8, f"{dati['pedaggio']:.2f} EUR", border=1, align="R")
    pdf.ln()

    y_tot = pdf.get_y() + 8
    pdf.set_xy(105, y_tot)
    pdf.set_fill_color(248, 249, 250)
    pdf.rect(105, y_tot, 90, 36, "F")
    pdf.set_draw_color(210, 215, 220)
    pdf.rect(105, y_tot, 90, 36)
    pdf.set_xy(110, y_tot + 4)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(45, 6, "Imponibile Totale:", ln=0)
    pdf.cell(35, 6, f"{dati['imponibile']:.2f} EUR", ln=1, align="R")
    pdf.set_xy(110, y_tot + 11)
    pdf.cell(45, 6, "IVA (22%):", ln=0)
    pdf.cell(35, 6, f"{dati['iva']:.2f} EUR", ln=1, align="R")
    pdf.set_xy(110, y_tot + 22)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(26, 82, 118)
    pdf.cell(45, 8, "TOTALE OFFERTA:", ln=0)
    pdf.cell(35, 8, f"{dati['totale']:.2f} EUR", ln=1, align="R")

    out = pdf.output(dest="S")
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin-1")

# ==========================================
# 5. GESTIONE SESSIONE & INTERFACCIA
# ==========================================
st.set_page_config(page_title="TruckFlow - Management Portal", layout="wide", initial_sidebar_state="expanded")

# Inizializziamo il DB al primo caricamento per creare le tabelle
try:
    init_db()
except Exception as e:
    st.error(f"Errore di connessione al Database. Verifica di aver inserito i Secrets in Streamlit! Dettaglio: {e}")

if "autenticato" not in st.session_state:
    st.session_state["autenticato"] = False
if "user_id" not in st.session_state:
    st.session_state["user_id"] = None
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "logo_path" not in st.session_state:
    st.session_state["logo_path"] = None

if not st.session_state["autenticato"]:
    st.title("🚛 TruckFlow B2B - Portale Accesso Cloud")
    scelta_modalita = st.radio("Scegli un'opzione:", ["Accedi", "Registra Nuova Azienda"], horizontal=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if scelta_modalita == "Accedi":
            st.subheader("Login Utente")
            user_login = st.text_input("Nome Utente / Azienda")
            pass_login = st.text_input("Password", type="password")
            if st.button("Accedi al Gestionale", type="primary"):
                utente_valido = verifica_login(user_login, pass_login)
                if utente_valido:
                    st.session_state["autenticato"] = True
                    st.session_state["user_id"] = utente_valido[0]
                    st.session_state["username"] = utente_valido[1]
                    st.success("Accesso effettuato!")
                    st.rerun()
                else:
                    st.error("Credenziali errate o account non trovato. Riprova.")
        else:
            st.subheader("Crea un Account Aziendale")
            user_reg = st.text_input("Scegli Nome Utente / Azienda")
            pass_reg = st.text_input("Crea Password", type="password")
            pass_reg_confirm = st.text_input("Conferma Password", type="password")

            if st.button("Registrati Subito", type="primary"):
                if pass_reg != pass_reg_confirm:
                    st.error("Le password non coincidono!")
                elif len(pass_reg) < 4:
                    st.error("La password deve contenere almeno 4 caratteri.")
                else:
                    ok, msg = registra_utente(user_reg, pass_reg)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
else:
    st.sidebar.title(f"👤 {st.session_state['username'].capitalize()}")
    st.sidebar.caption("Account Aziendale Attivo")
    st.sidebar.markdown("---")
    st.sidebar.subheader("🖼️ Personalizza PDF")
    logo_file = st.sidebar.file_uploader("Carica il tuo Logo (PNG/JPG)", type=["png", "jpg", "jpeg"])
    
    if logo_file:
        with open("logo_temp.png", "wb") as f:
            f.write(logo_file.getbuffer())
        st.session_state["logo_path"] = "logo_temp.png"
        st.sidebar.success("Logo caricato per questa sessione!")

    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Esci", use_container_width=True):
        st.session_state["autenticato"] = False
        st.session_state["user_id"] = None
        st.session_state["username"] = ""
        st.rerun()

    menu = ["Bolla CMR Professionale", "Generatore Preventivi", "Archivio e Statistiche"]
    scelta = st.sidebar.radio("Sezioni Gestionale:", menu)

    st.title("🚛 TruckFlow - Suite Gestionale")

    # --- SEZIONE BOLLA CMR ---
    if scelta == "Bolla CMR Professionale":
        st.header("📄 Emissione Bolla CMR")
        with st.form("form_cmr"):
            col1, col2 = st.columns(2)
            num_doc = col1.text_input("N° Documento", value="CMR-2026-001")
            data_doc = col2.date_input("Data Emissione").strftime("%d/%m/%Y")
            
            st.markdown("##### 🏢 Aziende Coinvolte")
            c1, c2 = st.columns(2)
            committente = c1.text_area("Committente / Mittente", placeholder="Nome azienda, P.IVA, Indirizzo")
            vettore = c2.text_area("Vettore (Tua Azienda)", placeholder="I tuoi dati aziendali")
            
            st.markdown("##### 📍 Logistica")
            c3, c4 = st.columns(2)
            r1 = c3.text_input("Luogo di Carico Principale", placeholder="Porto o Magazzino")
            s1 = c4.text_input("Luogo di Scarico Principale", placeholder="Destinazione merce")
            ora_ritiro = c3.time_input("Ora prevista ritiro")
            
            st.markdown("##### 🚚 Mezzo e Merce")
            c5, c6, c7 = st.columns(3)
            autista = c5.text_input("Nome Autista")
            trattore = c6.text_input("Targa Trattore")
            rimorchio = c7.text_input("Targa Rimorchio / Telaio")
            container = c5.text_input("N° Container / Sigillo")
            peso = c6.text_input("Peso Netto/Lordo (Kg)")
            merce = st.text_area("Natura della merce", placeholder="Descrizione dettagliata imballi e merce")
            note_oper = st.text_area("Note Operative Vettore")

            submit_cmr = st.form_submit_button("Genera Bolla CMR (PDF)", type="primary")

        if submit_cmr:
            dati_bolla = {
                "num_doc": num_doc, "data": data_doc, "ora": ora_ritiro.strftime("%H:%M"),
                "committente": committente, "vettore": vettore, "r1": r1, "s1": s1,
                "autista": autista, "trattore": trattore, "rimorchio": rimorchio,
                "container": container, "peso": peso, "merce": merce, "note": note_oper
            }
            pdf_bytes = crea_pdf_bolla(dati_bolla, st.session_state["logo_path"])
            st.success("Bolla CMR generata correttamente!")
            st.download_button("Scarica Bolla CMR in PDF", data=pdf_bytes, file_name=f"CMR_{num_doc}.pdf", mime="application/pdf")
            salva_cronologia(st.session_state["user_id"], "Emissione Bolla CMR", committente.split('\n')[0], f"Documento: {num_doc}")

    # --- SEZIONE PREVENTIVI ---
    elif scelta == "Generatore Preventivi":
        st.header("💰 Creazione Preventivo Avanzato")
        with st.form("form_preventivo"):
            cliente = st.text_input("Ragione Sociale Cliente", placeholder="Es. Rossi S.p.A.")
            c1, c2 = st.columns(2)
            partenza = c1.text_input("Città di Partenza", placeholder="Es. Genova")
            arrivo = c2.text_input("Città di Destinazione", placeholder="Es. Milano")
            ritorno = st.checkbox("Calcola anche il viaggio di ritorno", value=True)
            tariffa_km = st.number_input("Tariffa al Km (Euro)", min_value=0.5, value=1.5, step=0.1)
            
            submit_prev = st.form_submit_button("Elabora Costi e Crea Preventivo", type="primary")

        if submit_prev:
            if not cliente or not partenza or not arrivo:
                st.error("Compila tutti i campi fondamentali (Cliente, Partenza, Arrivo).")
            else:
                with st.spinner("Calcolo distanze e pedaggi in corso (tramite API)..."):
                    km_one_way, pedaggio_one_way = calcola_distanza_api(partenza, arrivo)
                    
                    if km_one_way:
                        moltiplicatore = 2 if ritorno else 1
                        km_tot = km_one_way * moltiplicatore
                        pedaggio_tot = pedaggio_one_way * moltiplicatore
                        costo_viaggio = km_tot * tariffa_km
                        imponibile = costo_viaggio + pedaggio_tot
                        iva = imponibile * 0.22
                        totale = imponibile + iva

                        dati_prev = {
                            "cliente": cliente, "partenza": partenza, "arrivo": arrivo, "is_ritorno": ritorno,
                            "km": km_tot, "tariffa": tariffa_km, "costo_viaggio": costo_viaggio,
                            "pedaggio": pedaggio_tot, "imponibile": imponibile, "iva": iva, "totale": totale
                        }
                        
                        pdf_bytes = crea_pdf_preventivo(dati_prev, st.session_state["logo_path"])
                        st.success(f"Distanza calcolata: {km_tot} Km Totali.")
                        st.download_button("Scarica Preventivo in PDF", data=pdf_bytes, file_name=f"Preventivo_{cliente}.pdf", mime="application/pdf")
                        salva_cronologia(st.session_state["user_id"], "Generazione Preventivo", cliente, f"{partenza} - {arrivo}", f"€ {totale:.2f}")
                    else:
                        st.error("Impossibile calcolare la tratta. Verifica i nomi delle città.")

    # --- SEZIONE ARCHIVIO E STATISTICHE ---
    elif scelta == "Archivio e Statistiche":
        st.header("📊 Archivio Storico e Dati")
        df_cronologia = carica_cronologia(st.session_state["user_id"])
        
        if df_cronologia.empty:
            st.info("Nessuna attività registrata per la tua azienda.")
        else:
            st.dataframe(df_cronologia, use_container_width=True, hide_index=True)
            
            st.subheader("Esporta Dati")
            csv = df_cronologia.to_csv(index=False).encode('utf-8')
            st.download_button("Scarica Archivio (CSV / Excel)", data=csv, file_name="archivio_aziendale.csv", mime="text/csv")
