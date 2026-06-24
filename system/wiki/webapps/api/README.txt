================================================================================
WEB-APPS API - VOLLSTAENDIGER LEITFADEN
================================================================================

# Portabilitaet: UNIVERSAL
# Zuletzt validiert: 2026-02-05
# Naechste Pruefung: 2027-02-05
# Quellen: MDN Web Docs, OpenAPI Specification, GraphQL Foundation, IETF RFC 6455

Stand: 2026-02-05
Status: VOLLSTAENDIG

================================================================================
INHALTSVERZEICHNIS
================================================================================
  1. Einfuehrung
  2. REST APIs
  3. GraphQL
  4. WebSockets
  5. Server-Sent Events (SSE)
  6. gRPC
  7. OpenAPI / Swagger
  8. Rate Limiting
  9. API-Sicherheit
  10. Best Practices
  11. Code-Beispiele
  12. Siehe auch

================================================================================
1. EINFUEHRUNG
================================================================================

APIs (Application Programming Interfaces) bilden das Rueckgrat moderner
Webanwendungen. Sie ermoeglichen die Kommunikation zwischen verschiedenen
Systemen, Services und Clients. Die Wahl der richtigen API-Architektur
haengt von den spezifischen Anforderungen des Projekts ab.

Hauptkategorien von Web-APIs:
  - Request-Response: REST, GraphQL, gRPC
  - Echtzeit: WebSockets, SSE
  - Asynchron: Message Queues, Webhooks

================================================================================
2. REST APIs
================================================================================

REST (Representational State Transfer) ist der am weitesten verbreitete
API-Stil fuer Webanwendungen.

GRUNDPRINZIPIEN
---------------
  1. Stateless: Jeder Request enthaelt alle notwendigen Informationen
  2. Client-Server: Klare Trennung von Verantwortlichkeiten
  3. Cacheable: Responses koennen gecached werden
  4. Uniform Interface: Einheitliche Schnittstelle
  5. Layered System: Schichtenarchitektur moeglich
  6. Code on Demand (optional): Server kann Code an Client senden

HTTP-METHODEN
-------------
  GET     - Ressource abrufen (idempotent, safe)
  POST    - Ressource erstellen (nicht idempotent)
  PUT     - Ressource vollstaendig ersetzen (idempotent)
  PATCH   - Ressource teilweise aktualisieren
  DELETE  - Ressource loeschen (idempotent)
  OPTIONS - Unterstuetzte Methoden abfragen
  HEAD    - Wie GET, aber nur Header

URL-DESIGN
----------
  Gut:
    GET    /api/v1/users           - Alle Benutzer
    GET    /api/v1/users/123       - Einzelner Benutzer
    GET    /api/v1/users/123/posts - Posts eines Benutzers
    POST   /api/v1/users           - Benutzer erstellen
    PUT    /api/v1/users/123       - Benutzer aktualisieren
    DELETE /api/v1/users/123       - Benutzer loeschen

  Schlecht:
    GET    /api/getUsers
    POST   /api/createUser
    GET    /api/deleteUser?id=123

HTTP-STATUS-CODES
-----------------
  2xx Erfolg:
    200 OK                    - Erfolgreicher Request
    201 Created               - Ressource erstellt
    204 No Content            - Erfolgreich, keine Daten

  3xx Weiterleitung:
    301 Moved Permanently     - Dauerhaft verschoben
    304 Not Modified          - Gecachte Version aktuell

  4xx Client-Fehler:
    400 Bad Request           - Ungueltige Anfrage
    401 Unauthorized          - Nicht authentifiziert
    403 Forbidden             - Keine Berechtigung
    404 Not Found             - Ressource nicht gefunden
    409 Conflict              - Konflikt (z.B. Duplikat)
    422 Unprocessable Entity  - Validierungsfehler
    429 Too Many Requests     - Rate Limit erreicht

  5xx Server-Fehler:
    500 Internal Server Error - Serverfehler
    502 Bad Gateway           - Gateway-Fehler
    503 Service Unavailable   - Service nicht verfuegbar

VERSIONIERUNG
-------------
  URL-Pfad (empfohlen):
    /api/v1/users
    /api/v2/users

  Header:
    Accept: application/vnd.myapi.v1+json

  Query-Parameter:
    /api/users?version=1

PAGINATION
----------
  Offset-basiert:
    GET /api/users?offset=20&limit=10

  Cursor-basiert (performanter):
    GET /api/users?cursor=abc123&limit=10

  Response mit Metadaten:
    {
      "data": [...],
      "pagination": {
        "total": 100,
        "page": 2,
        "per_page": 10,
        "next_cursor": "xyz789"
      }
    }

================================================================================
3. GRAPHQL
================================================================================

GraphQL ist eine Query-Sprache fuer APIs, entwickelt von Facebook (2015).

VORTEILE
--------
  - Client bestimmt exakt welche Daten benoetigt werden
  - Kein Over-fetching (zu viele Daten)
  - Kein Under-fetching (zu wenige Daten, mehrere Requests)
  - Stark typisiert durch Schema
  - Introspection - Schema kann abgefragt werden
  - Ein Endpoint fuer alles

SCHEMA DEFINITION
-----------------
  # Typen definieren
  type User {
    id: ID!
    username: String!
    email: String!
    posts: [Post!]!
    createdAt: DateTime!
  }

  type Post {
    id: ID!
    title: String!
    content: String!
    author: User!
    comments: [Comment!]!
  }

  # Queries (Lesen)
  type Query {
    user(id: ID!): User
    users(limit: Int, offset: Int): [User!]!
    post(id: ID!): Post
    posts(authorId: ID): [Post!]!
  }

  # Mutations (Schreiben)
  type Mutation {
    createUser(input: CreateUserInput!): User!
    updateUser(id: ID!, input: UpdateUserInput!): User!
    deleteUser(id: ID!): Boolean!
    createPost(input: CreatePostInput!): Post!
  }

  # Subscriptions (Echtzeit)
  type Subscription {
    postCreated: Post!
    userOnline(userId: ID!): User!
  }

  # Input-Typen
  input CreateUserInput {
    username: String!
    email: String!
    password: String!
  }

QUERY-BEISPIELE
---------------
  # Einfache Query
  query {
    user(id: "123") {
      username
      email
    }
  }

  # Verschachtelte Query
  query {
    user(id: "123") {
      username
      posts {
        title
        comments {
          text
        }
      }
    }
  }

  # Mutation
  mutation CreateUser($password: String!) {
    createUser(input: {
      username: "max"
      email: "max@example.com"
      password: $password
    }) {
      id
      username
    }
  }

N+1 PROBLEM LOESEN
------------------
  DataLoader verwenden fuer Batch-Loading:
    const userLoader = new DataLoader(async (ids) => {
      const users = await User.findByIds(ids);
      return ids.map(id => users.find(u => u.id === id));
    });

================================================================================
4. WEBSOCKETS
================================================================================

WebSockets ermoeglichen bidirektionale Echtzeit-Kommunikation.

EIGENSCHAFTEN
-------------
  - Persistente Verbindung
  - Bidirektional (Server und Client koennen senden)
  - Niedriger Overhead nach Handshake
  - Protokoll: ws:// oder wss:// (verschluesselt)

ANWENDUNGSFAELLE
----------------
  - Chat-Anwendungen
  - Live-Notifications
  - Echtzeit-Kollaboration (z.B. Docs)
  - Gaming
  - Live-Dashboards
  - Boersenticker

SERVER-BEISPIEL (Node.js mit ws)
--------------------------------
  import { WebSocketServer } from 'ws';

  const wss = new WebSocketServer({ port: 8080 });

  wss.on('connection', (ws) => {
    console.log('Client verbunden');

    ws.on('message', (data) => {
      const message = JSON.parse(data);

      // Broadcast an alle Clients
      wss.clients.forEach((client) => {
        if (client.readyState === WebSocket.OPEN) {
          client.send(JSON.stringify(message));
        }
      });
    });

    ws.on('close', () => {
      console.log('Client getrennt');
    });
  });

CLIENT-BEISPIEL
---------------
  const ws = new WebSocket('wss://api.example.com/ws');

  ws.onopen = () => {
    console.log('Verbunden');
    ws.send(JSON.stringify({ type: 'subscribe', channel: 'updates' }));
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleMessage(data);
  };

  ws.onclose = () => {
    console.log('Verbindung geschlossen');
    // Reconnect-Logik hier
  };

  ws.onerror = (error) => {
    console.error('WebSocket Fehler:', error);
  };

SOCKET.IO (Abstraktionslayer)
-----------------------------
  Vorteile:
    - Automatisches Fallback (Long-Polling)
    - Rooms und Namespaces
    - Auto-Reconnect
    - Acknowledgements

================================================================================
5. SERVER-SENT EVENTS (SSE)
================================================================================

SSE ermoeglicht unidirektionales Streaming vom Server zum Client.

VORTEILE GEGENUEBER WEBSOCKETS
------------------------------
  - Einfacher zu implementieren
  - HTTP-basiert (keine spezielle Infrastruktur)
  - Automatisches Reconnect
  - Event-IDs fuer Resume nach Verbindungsabbruch

SERVER-BEISPIEL (Node.js/Express)
---------------------------------
  app.get('/events', (req, res) => {
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');

    const sendEvent = (data) => {
      res.write(`id: ${Date.now()}\n`);
      res.write(`event: message\n`);
      res.write(`data: ${JSON.stringify(data)}\n\n`);
    };

    // Periodische Updates
    const interval = setInterval(() => {
      sendEvent({ time: new Date().toISOString() });
    }, 1000);

    req.on('close', () => {
      clearInterval(interval);
    });
  });

CLIENT-BEISPIEL
---------------
  const eventSource = new EventSource('/events');

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Nachricht:', data);
  };

  eventSource.addEventListener('custom-event', (event) => {
    console.log('Custom Event:', event.data);
  });

  eventSource.onerror = () => {
    console.log('Fehler - Reconnect wird versucht...');
  };

================================================================================
6. gRPC
================================================================================

gRPC ist ein High-Performance RPC-Framework von Google.

EIGENSCHAFTEN
-------------
  - Protocol Buffers als Serialisierungsformat
  - HTTP/2 (Multiplexing, Header-Kompression)
  - Stark typisiert
  - Bidirektionales Streaming
  - Code-Generierung fuer viele Sprachen

PROTO-DATEI BEISPIEL
--------------------
  syntax = "proto3";

  package user;

  service UserService {
    rpc GetUser(GetUserRequest) returns (User);
    rpc ListUsers(ListUsersRequest) returns (stream User);
    rpc CreateUser(CreateUserRequest) returns (User);
  }

  message User {
    string id = 1;
    string name = 2;
    string email = 3;
  }

  message GetUserRequest {
    string id = 1;
  }

  message ListUsersRequest {
    int32 page_size = 1;
    string page_token = 2;
  }

  message CreateUserRequest {
    string name = 1;
    string email = 2;
  }

EINSATZGEBIETE
--------------
  - Microservices-Kommunikation (intern)
  - Mobile Apps (effizient bei schlechter Verbindung)
  - Polyglotte Systeme (verschiedene Programmiersprachen)

================================================================================
7. OPENAPI / SWAGGER
================================================================================

OpenAPI Specification (OAS) ist der Standard fuer REST-API-Dokumentation.

BEISPIEL (openapi.yaml)
-----------------------
  openapi: 3.0.3
  info:
    title: User API
    version: 1.0.0
    description: API zur Benutzerverwaltung

  servers:
    - url: https://api.example.com/v1

  paths:
    /users:
      get:
        summary: Liste aller Benutzer
        parameters:
          - name: limit
            in: query
            schema:
              type: integer
              default: 10
        responses:
          '200':
            description: Erfolgreich
            content:
              application/json:
                schema:
                  type: array
                  items:
                    $ref: '#/components/schemas/User'

      post:
        summary: Benutzer erstellen
        requestBody:
          required: true
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CreateUser'
        responses:
          '201':
            description: Erstellt

  components:
    schemas:
      User:
        type: object
        properties:
          id:
            type: string
          name:
            type: string
          email:
            type: string
            format: email

TOOLS
-----
  - Swagger UI: Interaktive Dokumentation
  - Swagger Editor: OpenAPI-Dateien bearbeiten
  - Swagger Codegen: Client/Server-Code generieren
  - Redoc: Alternative Dokumentations-UI
  - Postman: API-Testing mit OpenAPI-Import

================================================================================
8. RATE LIMITING
================================================================================

Rate Limiting schuetzt APIs vor Ueberlastung und Missbrauch.

ALGORITHMEN
-----------
  Token Bucket:
    - Tokens werden kontinuierlich hinzugefuegt
    - Request verbraucht Token
    - Erlaubt Bursts

  Sliding Window:
    - Zaehlt Requests in gleitendem Zeitfenster
    - Genauer als Fixed Window

  Fixed Window:
    - Zaehlt Requests pro Zeitfenster
    - Einfach zu implementieren

RESPONSE-HEADER
---------------
  X-RateLimit-Limit: 100        # Max Requests
  X-RateLimit-Remaining: 45     # Verbleibende Requests
  X-RateLimit-Reset: 1625140800 # Timestamp Reset
  Retry-After: 60               # Sekunden bis Retry

IMPLEMENTIERUNG (Express.js)
----------------------------
  import rateLimit from 'express-rate-limit';

  const limiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 Minuten
    max: 100, // Max 100 Requests pro Fenster
    message: { error: 'Zu viele Anfragen' },
    standardHeaders: true,
    legacyHeaders: false,
  });

  app.use('/api/', limiter);

================================================================================
9. API-SICHERHEIT
================================================================================

  - HTTPS immer verwenden
  - API-Keys fuer einfache Authentifizierung
  - OAuth 2.0 / JWT fuer komplexe Szenarien
  - Input-Validierung (nie Client vertrauen)
  - CORS korrekt konfigurieren
  - Rate Limiting aktivieren
  - Sensitive Daten nicht in URLs
  - Logging und Monitoring

================================================================================
10. BEST PRACTICES
================================================================================

  1. Konsistente Namenskonventionen (snake_case oder camelCase)
  2. Aussagekraeftige Fehlermeldungen mit Fehlercode
  3. Pagination fuer Listen-Endpoints
  4. Versionierung von Anfang an
  5. HATEOAS fuer Discoverability (optional)
  6. Idempotenz wo moeglich
  7. Caching-Header setzen
  8. Kompression aktivieren (gzip)
  9. Request-IDs fuer Tracing
  10. Health-Check Endpoint (/health)

================================================================================
11. CODE-BEISPIELE
================================================================================

EXPRESS.JS REST API
-------------------
  import express from 'express';
  import cors from 'cors';
  import helmet from 'helmet';

  const app = express();

  app.use(helmet());
  app.use(cors());
  app.use(express.json());

  // Error Handler
  app.use((err, req, res, next) => {
    console.error(err);
    res.status(500).json({
      error: {
        code: 'INTERNAL_ERROR',
        message: 'Ein Fehler ist aufgetreten'
      }
    });
  });

  // Routes
  app.get('/api/v1/users', async (req, res) => {
    const { limit = 10, offset = 0 } = req.query;
    const users = await User.findAll({ limit, offset });
    res.json({ data: users });
  });

  app.listen(3000);

================================================================================
SIEHE AUCH
================================================================================

  BACH Wiki:
    wiki/python/api/
    wiki/informatik/software_architektur/
    wiki/webapps/authentifizierung/
    wiki/webapps/datenbanken/

  Externe Ressourcen:
    https://restfulapi.net/
    https://graphql.org/learn/
    https://swagger.io/specification/
    https://grpc.io/docs/

================================================================================
