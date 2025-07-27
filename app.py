from fastapi import FastAPI, UploadFile, File, Request, Form, Cookie
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import os
import requests
import google.generativeai as genai
from PIL import Image
import io
import firebase_admin
from firebase_admin import credentials, auth as firebase_auth
from dotenv import load_dotenv
import subprocess


load_dotenv()

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY")
FIREBASE_ADMIN_CREDENTIALS = os.environ.get("FIREBASE_ADMIN_CREDENTIALS", "firebase-admin.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_ADMIN_CREDENTIALS)
    firebase_admin.initialize_app(cred)

app = FastAPI()

# Mount static files at /static
app.mount("/static", StaticFiles(directory="public"), name="static")

@app.get("/")
def get_index(firebase_id_token: str = Cookie(None)):
    if not firebase_id_token:
        return FileResponse("public/index.html")
    try:
        decoded_token = firebase_auth.verify_id_token(firebase_id_token)
        return FileResponse("public/dashboard.html")
    except Exception:
        return FileResponse("public/index.html")

@app.get("/login")
def get_login(firebase_id_token: str = Cookie(None)):
    if not firebase_id_token:
        return FileResponse("public/login.html")
    try:
        decoded_token = firebase_auth.verify_id_token(firebase_id_token)
        return FileResponse("public/dashboard.html")
    except Exception:
        return FileResponse("public/login.html")

@app.get("/register")
def get_register():
    return FileResponse("public/register.html")

@app.get("/dashboard")
def get_dashboard(firebase_id_token: str = Cookie(None)):
    if not firebase_id_token:
        return FileResponse("public/login.html")
    try:
        decoded_token = firebase_auth.verify_id_token(firebase_id_token)
        return FileResponse("public/dashboard.html")
    except Exception:
        return FileResponse("public/login.html")

@app.post("/analyze")
async def analyze_image(file: UploadFile = File(...)):
    genai.configure(api_key=GOOGLE_API_KEY)
    contents = await file.read()
    image = Image.open(io.BytesIO(contents))

    img_bytes = io.BytesIO()
    image.save(img_bytes, format="PNG")
    img_bytes = img_bytes.getvalue()

    with open("cleaned_carcinogens.csv", "r", encoding="utf-8") as csv_file:
        csv_content = csv_file.read()

    # Text explanation for the IARC Monographs
    iarc_explanation = ("\n\nLegend:\n"
        "🟥 Group 1 – Carcinogenic to humans: Sufficient evidence in humans.\n"
        "🟧 Group 2A – Probably carcinogenic: Limited evidence in humans, sufficient evidence in animals.\n"
        "🟨 Group 2B – Possibly carcinogenic: Limited evidence in humans, insufficient evidence in animals.\n"
        "🟩 Group 3 – Not classifiable or not carcinogenic: Inadequate evidence or not listed.\n")

    prompt = (
    "You are a toxicologist and regulatory analyst expert in evaluating product safety, especially based on the IARC Monographs on Carcinogenic Risks to Humans.\n\n"
    "Your job is to extract all ingredients from the product label image and classify each one according to IARC Monographs Group 1, 2A, 2B, or 3. If the name is commercial, brand-based, abbreviated (e.g., 'E-numbers'), or in common terms, identify the equivalent scientific or chemical name from the IARC list provided.\n\n"
    "Use this IARC reference table for classification (chemical name | group | explanation):\n\n"
    f"{csv_content}\n\n"
    "And extract each ingredient you can find in the image. Match it to the IARC reference table.\n"
    "Output must follow this format (no extra explanation or text):\n\n"
    "**Ingredient | IARC Classification | Explanation (if needed)**\n\n"
    "\nLegend:\n"
    "🟥 = Carcinogenic\n"
    "🟧 = Probably carcinogenic\n"
    "🟨 = Possibly carcinogenic\n"
    "🟩 = Not classifiable or not carcinogenic\n\n"
    
    "If the classification is not 🟩, include a short explanation (max 12 words or less)."
    "Identify the language of the text in the image and respond in that language."
    )

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content([
        prompt,
        {
            "mime_type": "image/png",
            "data": img_bytes
        }
    ])
    return JSONResponse({"result": response.text + iarc_explanation})

@app.post("/register_user")
async def register_user(request: Request):
    form = await request.form()
    email = form.get("email")
    password = form.get("password")
    username = form.get("username")
    try:
        user = firebase_auth.create_user(
            email=email,
            password=password,
            display_name=username
        )
        return {"success": True, "message": "User registered successfully!"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/login_user")
async def login_user(request: Request, firebase_id_token: str = Cookie(None)):
    # 1. Check for valid cookie first
    if firebase_id_token:
        try:
            decoded_token = firebase_auth.verify_id_token(firebase_id_token)
            # Valid token, return JSON for frontend redirect
            response = JSONResponse({"success": True, "message": "Already logged in."})
            response.set_cookie(
                key="firebase_id_token",
                value=firebase_id_token,
                httponly=True,
                max_age=60*60*24*30,  # 30 days
                samesite="lax"
            )
            return response
        except Exception:
            pass  # Invalid/expired token, continue to login

    # 2. If no valid cookie, process login form
    form = await request.form()
    email = form.get("email")
    password = form.get("password")
    
    if not email or not password:
        return JSONResponse({"success": False, "message": "Email and password are required."})
    
    if not FIREBASE_API_KEY:
        return JSONResponse({"success": False, "message": "Firebase API key not configured."})
    
    try:
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        resp = requests.post(url, json=payload)
        
        if resp.status_code == 200:
            id_token = resp.json().get("idToken")
            response = JSONResponse({"success": True, "message": "Login successful!"})
            response.set_cookie(
                key="firebase_id_token",
                value=id_token,
                httponly=True,
                max_age=60*60*24*30,  # 30 days
                samesite="lax"
            )
            return response
        else:
            error_data = resp.json()
            msg = error_data.get("error", {}).get("message", "Login failed.")
            return JSONResponse({"success": False, "message": msg})
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Login error: {str(e)}"})
