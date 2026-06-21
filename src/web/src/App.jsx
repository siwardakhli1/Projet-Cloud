import { useState, useEffect, useRef } from "react";
import api from "./services/api";
import { uploadFileToBlob } from "./services/blob";
import { startSignalR } from "./services/signalr";

const STATUS_COLORS = {
  CREATED: "#64748b",
  UPLOADED: "#2563eb",
  QUEUED: "#7c3aed",
  PROCESSING: "#d97706",
  PROCESSED: "#16a34a",
  ERROR: "#dc2626",
};

function App() {
  const [file, setFile] = useState(null);
  const [jobId, setJobId] = useState("");
  const [status, setStatus] = useState("");
  const [tags, setTags] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState([]);

  const connRef = useRef(null);

  // Connexion SignalR au montage du composant.
  useEffect(() => {
    let active = true;
    startSignalR((event) => {
      // À chaque notification reçue depuis les Functions.
      setEvents((prev) => [event, ...prev].slice(0, 50));
      // Si l'événement concerne le job courant, on met à jour l'affichage.
      setJobId((currentId) => {
        if (event.documentId === currentId) {
          setStatus(event.status);
          if (event.tags) setTags(event.tags);
        }
        return currentId;
      });
    })
      .then((conn) => {
        if (!active) {
          conn.stop();
          return;
        }
        connRef.current = conn;
        setConnected(true);
      })
      .catch((err) => {
        console.error("SignalR connexion échouée:", err);
        setConnected(false);
      });

    return () => {
      active = false;
      if (connRef.current) connRef.current.stop();
    };
  }, []);

  const handleInitAndUpload = async () => {
    if (!file) {
      setMessage("Veuillez sélectionner un fichier.");
      return;
    }
    try {
      setLoading(true);
      setMessage("");
      setTags([]);

      const initResponse = await api.post("/jobs", {
        fileName: file.name,
        contentType: file.type || "application/octet-stream",
      });

      const { jobId, uploadUrl, status } = initResponse.data;
      setJobId(jobId);
      setStatus(status);

      await uploadFileToBlob(uploadUrl, file);
      setMessage("Fichier uploadé. Suivi du traitement en temps réel ci-dessous.");
    } catch (error) {
      console.error(error);
      setMessage("Erreur pendant l'initialisation ou l'upload.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: "40px auto", fontFamily: "Arial, sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Cloud Document Processing</h1>
        <span style={{
          padding: "4px 10px", borderRadius: 999, fontSize: 13, color: "#fff",
          background: connected ? "#16a34a" : "#dc2626",
        }}>
          {connected ? "Temps réel connecté" : "Déconnecté"}
        </span>
      </div>

      <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />

      <div style={{ marginTop: 16 }}>
        <button onClick={handleInitAndUpload} disabled={loading}>
          {loading ? "Chargement..." : "Initialiser et uploader"}
        </button>
      </div>

      {jobId && (
        <div style={{ marginTop: 24 }}>
          <p><strong>Job ID :</strong> {jobId}</p>
          <p>
            <strong>Status :</strong>{" "}
            <span style={{
              color: "#fff", padding: "2px 10px", borderRadius: 6,
              background: STATUS_COLORS[status] || "#64748b",
            }}>
              {status}
            </span>
          </p>
          {tags.length > 0 && (
            <p><strong>Tags :</strong> {tags.join(", ")}</p>
          )}
        </div>
      )}

      {message && (
        <div style={{ marginTop: 24 }}><p>{message}</p></div>
      )}

      <div style={{ marginTop: 32 }}>
        <h2 style={{ fontSize: 18 }}>Flux d'événements temps réel</h2>
        {events.length === 0 && <p style={{ color: "#94a3b8" }}>En attente d'événements…</p>}
        <ul style={{ listStyle: "none", padding: 0, fontSize: 14 }}>
          {events.map((e, i) => (
            <li key={i} style={{ padding: "4px 0", borderBottom: "1px dashed #e2e8f0" }}>
              <strong style={{ color: STATUS_COLORS[e.status] || "#64748b" }}>
                {e.status}
              </strong>
              {" — "}doc {e.documentId?.slice(0, 8)}… — {e.message}
              {e.tags ? ` [${e.tags.join(", ")}]` : ""}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default App;
