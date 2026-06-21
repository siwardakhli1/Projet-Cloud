import * as signalR from "@microsoft/signalr";
import api from "./api";

/**
 * Crée et démarre une connexion SignalR (mode Serverless).
 *
 * 1. Appelle le backend FastAPI (POST /signalr/negotiate) qui renvoie
 *    { url, accessToken } pour se connecter au service SignalR.
 * 2. Ouvre la connexion et écoute l'événement "documentUpdate".
 *
 * onEvent(event) est appelé à chaque notification reçue.
 * Retourne la connexion (pour pouvoir l'arrêter via conn.stop()).
 */
export async function startSignalR(onEvent) {
  // Étape negotiate : on demande l'URL + token à notre backend.
  const negotiate = await api.post("/signalr/negotiate");
  const { url, accessToken } = negotiate.data;

  const conn = new signalR.HubConnectionBuilder()
    .withUrl(url, { accessTokenFactory: () => accessToken })
    .withAutomaticReconnect()
    .configureLogging(signalR.LogLevel.Information)
    .build();

  // Réception des événements envoyés par les Functions.
  conn.on("documentUpdate", (event) => {
    onEvent(event);
  });

  await conn.start();
  return conn;
}
