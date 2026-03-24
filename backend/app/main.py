from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import micrologs, assets, agent

app = FastAPI(
    title="MEW API",
    description="MEW 後端模組化架構：記憶、資產與 Agent 狀態管理",
    version="2.2.0"
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# router
app.include_router(micrologs.router, prefix="/api/v1/micrologs", tags=["Memory"])
app.include_router(assets.router, prefix="/api/v1/assets", tags=["Assets"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])

@app.get("/")
def read_root():
    return {"message": "MEW API v2.2 is online!"}