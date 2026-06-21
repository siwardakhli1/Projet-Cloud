from fastapi import FastAPI
from .routes_jobs import router as jobs_router
from .routes_signalr import router as signalr_router
from .routes_documents import router as documents_router
from fastapi.middleware.cors import CORSMiddleware

origins = ["*"]
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


app.include_router(jobs_router)
app.include_router(signalr_router)
app.include_router(documents_router)


@app.get("/health")
def health():
    return {"status": "ok"}
