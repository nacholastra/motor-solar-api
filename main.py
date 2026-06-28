from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import os
from datetime import datetime
from typing import Optional
import bcrypt
import uuid

from motor_solar import calcular_simulacion, SimulacionError

app = FastAPI(title="SolarFlow SaaS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción final, cambiaremos "*" por ["https://tu-dominio.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.getenv("MONGO_URI", "")
client = MongoClient(MONGO_URI)
db = client["solar_saas_db"]
empresas_collection = db["empresas"]
leads_collection = db["leads"]

class EmpresaRegistro(BaseModel):
    nombre_empresa: str
    email: str
    password: str

class EmpresaLogin(BaseModel):
    email: str
    password: str

class Lead(BaseModel):
    empresa_id: str
    gasto_mensual: float
    anos_estimados: int
    tipo_cliente: str
    pais: str
    nombre: str
    telefono: str
    email: str
    estado: str = "nuevo"
    notas: str = ""

class LeadUpdate(BaseModel):
    estado: str = None
    notas: str = None

class SimulacionRequest(BaseModel):
    gasto_mensual: float
    tipo_cliente: str
    region: str = "madrid"
    anos_estimados: int = 20
    consumo_kwh: Optional[float] = None

def hash_password(password: str) -> str:
    # Genera una "sal" aleatoria y encripta la contraseña (Estándar de la industria)
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verificar_password(plain_password: str, hashed_password: str) -> bool:
    # Compara la contraseña limpia con el hash de la base de datos
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def obtener_empresa_actual(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token de sesión no proporcionado")
    
    token = authorization.split(" ")[1]
    empresa = empresas_collection.find_one({"sesion_token": token})
    if not empresa:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    return empresa

@app.post("/api/v1/auth/registro")
async def registrar_empresa(datos: EmpresaRegistro):
    if empresas_collection.find_one({"email": datos.email}):
        raise HTTPException(status_code=400, detail="Este email ya está registrado por otra empresa")
    
    empresa_id = str(uuid.uuid4())[:12]
    
    nueva_empresa = {
        "empresa_id": empresa_id,
        "nombre_empresa": datos.nombre_empresa,
        "email": datos.email,
        "password_hash": hash_password(datos.password), # Guardado de forma 100% segura
        "fecha_registro": datetime.now().isoformat(),
        "sesion_token": None
    }
    empresas_collection.insert_one(nueva_empresa)
    return {"mensaje": "Cuenta de empresa creada con éxito"}

@app.post("/api/v1/auth/login")
async def login_empresa(datos: EmpresaLogin):
    # 1. Buscamos a la empresa solo por email
    empresa = empresas_collection.find_one({"email": datos.email})
    
    # 2. Si no existe, o si la contraseña no coincide con el hash, rechazamos
    if not empresa or not verificar_password(datos.password, empresa["password_hash"]):
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")
    
    nuevo_token = str(uuid.uuid4())
    empresas_collection.update_one({"_id": empresa["_id"]}, {"$set": {"sesion_token": nuevo_token}})
    
    return {
        "token": nuevo_token, 
        "empresa_id": empresa["empresa_id"], 
        "nombre_empresa": empresa["nombre_empresa"]
    }

@app.get("/api/v1/widget/config/{empresa_id}")
async def obtener_config_widget(empresa_id: str):
    empresa = empresas_collection.find_one({"empresa_id": empresa_id})
    if not empresa:
        return {"nombre_empresa": "Tu Instalador Solar"}
    return {"nombre_empresa": empresa["nombre_empresa"]}

@app.post("/api/v1/simular")
async def simular_instalacion(datos: SimulacionRequest):
    try:
        return calcular_simulacion(
            gasto_mensual=datos.gasto_mensual,
            tipo_cliente=datos.tipo_cliente,
            region=datos.region,
            anos_proyeccion=datos.anos_estimados,
            consumo_mensual_kwh=datos.consumo_kwh,
        )
    except SimulacionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Error interno al calcular la simulación.")

@app.post("/api/v1/leads")
async def crear_lead(lead: Lead):
    try:
        lead_dict = lead.dict()
        lead_dict["fecha"] = datetime.now().isoformat()
        leads_collection.insert_one(lead_dict)
        return {"mensaje": "Lead guardado correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error del servidor al guardar el lead")

@app.get("/api/v1/leads", dependencies=[Depends(obtener_empresa_actual)])
async def obtener_mis_leads(authorization: str = Header(None)):
    empresa = obtener_empresa_actual(authorization)
    leads = list(leads_collection.find({"empresa_id": empresa["empresa_id"]}, {"_id": 0}))
    leads.sort(key=lambda x: x.get("fecha", ""), reverse=True)
    return leads

@app.put("/api/v1/leads/{fecha}", dependencies=[Depends(obtener_empresa_actual)])
async def actualizar_lead(fecha: str, update_data: LeadUpdate, authorization: str = Header(None)):
    empresa = obtener_empresa_actual(authorization)
    update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
    
    resultado = leads_collection.update_one({"fecha": fecha, "empresa_id": empresa["empresa_id"]}, {"$set": update_dict})
    if resultado.modified_count == 0:
        raise HTTPException(status_code=404, detail="Lead no encontrado o no tienes permiso")
    return {"mensaje": "Actualizado"}

@app.delete("/api/v1/leads/{fecha}", dependencies=[Depends(obtener_empresa_actual)])
async def borrar_lead(fecha: str, authorization: str = Header(None)):
    empresa = obtener_empresa_actual(authorization)
    
    # Eliminación estricta utilizando el horario (fecha) como identificador único
    resultado = leads_collection.delete_one({
        "fecha": fecha, 
        "empresa_id": empresa["empresa_id"]
    })
    
    # Verificamos si realmente se encontró y borró un cliente con ese horario
    if resultado.deleted_count == 0:
        raise HTTPException(status_code=404, detail="No se encontró un cliente con ese horario exacto.")
        
    return {"estado": "éxito", "mensaje": "Cliente eliminado correctamente."}
