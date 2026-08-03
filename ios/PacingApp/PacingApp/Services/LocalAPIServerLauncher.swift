import Foundation

/// Résultat du démarrage ou test du serveur FastAPI local.
enum ServerLaunchResult: Sendable {
    case alreadyRunning
    case started(String)
    case unreachable(String)
    case unsupportedPlatform
}

/// Lance `uvicorn` depuis le dépôt Pacing (macOS uniquement).
final class LocalAPIServerLauncher: @unchecked Sendable {
    static let shared = LocalAPIServerLauncher()

    /// Point d'entrée FastAPI du dépôt (``pacing.api.main:app``, pas ``pacing.app.main``).
    static let uvicornTarget = "pacing.api.main:app"

    private var serverProcess: Process?
    private let lock = NSLock()

    private init() {}

    /// Chemin du dépôt Pacing (contient ``.venv``).
    var defaultProjectPath: String {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Desktop/Pacing")
            .path
    }

    /// Démarre uvicorn si l'API ne répond pas encore.
    ///
    /// Args:
    ///     projectPath (String): Racine du repo Pacing.
    ///     host (String): Hôte HTTP (ex. ``127.0.0.1``).
    ///     port (Int): Port HTTP.
    ///
    /// Returns:
    ///     ServerLaunchResult: État après tentative de démarrage.
    func startIfNeeded(projectPath: String, host: String, port: Int) -> ServerLaunchResult {
        #if os(macOS)
        lock.lock()
        defer { lock.unlock() }

        if serverProcess?.isRunning == true {
            return .alreadyRunning
        }

        let expanded = (projectPath as NSString).expandingTildeInPath
        let uvicornURL = URL(fileURLWithPath: expanded)
            .appendingPathComponent(".venv/bin/uvicorn")

        guard FileManager.default.isExecutableFile(atPath: uvicornURL.path) else {
            return .unreachable(
                "uvicorn introuvable dans \(expanded)/.venv/bin/. "
                + "Active le venv : source .venv/bin/activate && pip install -e ."
            )
        }

        let process = Process()
        process.executableURL = uvicornURL
        process.arguments = [
            Self.uvicornTarget,
            "--reload",
            "--host", host,
            "--port", String(port),
        ]
        process.currentDirectoryURL = URL(fileURLWithPath: expanded)

        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = expanded
        process.environment = env

        let logURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("pacing-uvicorn.log")
        if FileManager.default.fileExists(atPath: logURL.path) {
            try? FileManager.default.removeItem(at: logURL)
        }
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        if let logHandle = try? FileHandle(forWritingTo: logURL) {
            process.standardOutput = logHandle
            process.standardError = logHandle
        }

        do {
            try process.run()
            serverProcess = process
            let cmd = "uvicorn \(Self.uvicornTarget) --reload --host \(host) --port \(port)"
            return .started(cmd)
        } catch {
            return .unreachable("Impossible de lancer uvicorn : \(error.localizedDescription)")
        }
        #else
        return .unsupportedPlatform
        #endif
    }

    /// Arrête le processus uvicorn lancé par l'app (macOS).
    func stop() {
        #if os(macOS)
        lock.lock()
        defer { lock.unlock() }
        serverProcess?.terminate()
        serverProcess = nil
        #endif
    }
}
