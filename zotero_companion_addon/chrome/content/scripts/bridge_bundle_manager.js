"use strict";

var ZoteroAgentBridgeBundleManager = (() => {
  const BUNDLE_SCHEMA_VERSION = 1;
  const PROTOCOL_VERSION = 2;
  const PRODUCT_SCOPE = "zotero-pi-only";
  const LEGACY_BUNDLED_BASELINE_VERSION = "0.3.5";
  const BUNDLE_PREFIX = "bridge/windows-x64/";
  const INSTALL_STATE = "install-state.json";
  const INSTALL_LOCK = "install.lock";
  const LOCK_STALE_MS = 120000;
  const LOCK_WAIT_MS = 30000;

  class BundleError extends Error {
    constructor(code, message, details = null) {
      super(message);
      this.name = "BundleError";
      this.code = code;
      this.details = details;
    }
  }

  function normalizeManifestPath(value) {
    const path = String(value || "");
    if (!path || path.includes("\\") || path.includes("\0") || path.startsWith("/")) {
      throw new BundleError("bundle_path_invalid", `Unsafe Bundle path: ${path}`);
    }
    const parts = path.split("/");
    if (parts.some((part) => !part || part === "." || part === "..") || /^[A-Za-z]:/.test(parts[0])) {
      throw new BundleError("bundle_path_invalid", `Unsafe Bundle path: ${path}`);
    }
    return parts.join("/");
  }

  function validateManifestShape(manifest, { protocolVersion, productScope = null } = {}) {
    if (!manifest || typeof manifest !== "object") {
      throw new BundleError("bundle_manifest_invalid", "Bridge Bundle manifest must be an object");
    }
    if (manifest.bundle_schema_version !== BUNDLE_SCHEMA_VERSION) {
      throw new BundleError("bundle_schema_unsupported", "Unsupported Bridge Bundle schema");
    }
    if (manifest.protocol_version !== protocolVersion) {
      throw new BundleError("bundle_protocol_unsupported", "Unsupported Bridge lifecycle protocol");
    }
    if (productScope !== null && manifest.product_scope !== productScope) {
      throw new BundleError("bundle_product_scope_unsupported", "Bridge Bundle is not scoped to Zotero Pi Assistant");
    }
    if (manifest.distribution !== "xpi-bundled" || manifest.platform !== "windows" || manifest.architecture !== "x64") {
      throw new BundleError("bundle_platform_unsupported", "Bridge Bundle is not Windows x64");
    }
    if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(String(manifest.bridge_version || ""))) {
      throw new BundleError("bundle_version_invalid", "Bridge Bundle version is invalid");
    }
    const entrypoint = normalizeManifestPath(manifest.entrypoint);
    if (manifest.sentinel !== ".zab-bundle-installed.json") {
      throw new BundleError("bundle_sentinel_invalid", "Bridge Bundle sentinel is invalid");
    }
    if (!Array.isArray(manifest.files) || !manifest.files.length) {
      throw new BundleError("bundle_manifest_invalid", "Bridge Bundle contains no files");
    }
    const seen = new Set();
    let previous = null;
    const files = manifest.files.map((record) => {
      if (!record || typeof record !== "object") {
        throw new BundleError("bundle_manifest_invalid", "Bridge Bundle file record is invalid");
      }
      const path = normalizeManifestPath(record.path);
      if (seen.has(path)) {
        throw new BundleError("bundle_path_duplicate", `Duplicate Bundle path: ${path}`);
      }
      if (previous !== null && previous > path) {
        throw new BundleError("bundle_manifest_unsorted", "Bridge Bundle file records must be sorted");
      }
      if (!Number.isSafeInteger(record.size) || record.size < 0 || !/^[0-9a-f]{64}$/.test(String(record.sha256 || ""))) {
        throw new BundleError("bundle_manifest_invalid", `Bridge Bundle metadata is invalid: ${path}`);
      }
      seen.add(path);
      previous = path;
      return { path, size: record.size, sha256: String(record.sha256) };
    });
    if (!seen.has(entrypoint)) {
      throw new BundleError("bundle_entrypoint_missing", "Bridge entrypoint is not listed in Bundle files");
    }
    return { ...manifest, entrypoint, files };
  }

  function validateManifest(manifest) {
    return validateManifestShape(manifest, { protocolVersion: PROTOCOL_VERSION, productScope: PRODUCT_SCOPE });
  }

  function validateLegacyManifest(manifest) {
    return validateManifestShape(manifest, { protocolVersion: 1 });
  }

  function validateBundledManifest(manifest, addonVersion) {
    if (manifest?.protocol_version === PROTOCOL_VERSION) {
      return validateManifest(manifest);
    }
    if (
      manifest?.protocol_version === 1
      && addonVersion === LEGACY_BUNDLED_BASELINE_VERSION
      && manifest.bridge_version === LEGACY_BUNDLED_BASELINE_VERSION
    ) {
      return validateLegacyManifest(manifest);
    }
    throw new BundleError(
      "bundle_protocol_unsupported",
      "Bundled Bridge lifecycle protocol is not valid for this add-on version",
      {
        addon_version: addonVersion,
        bridge_version: manifest?.bridge_version || null,
        protocol_version: manifest?.protocol_version ?? null,
      },
    );
  }

  function integerOrNull(value) {
    const result = Number(value);
    return Number.isInteger(result) && result >= 0 ? result : null;
  }

  function normalizeInstallState(value = {}) {
    if (!value || typeof value !== "object") {
      throw new BundleError("bundle_install_state_invalid", "Bridge Bundle install state is invalid");
    }
    if (value.state_schema_version !== undefined && value.state_schema_version !== 1) {
      throw new BundleError("bundle_install_state_invalid", "Bridge Bundle install state schema is unsupported");
    }
    return {
      ...value,
      state_schema_version: 1,
      current_version: value.current_version || null,
      current_protocol_version: integerOrNull(value.current_protocol_version),
      current_product_scope: value.current_product_scope || null,
      last_known_good: value.last_known_good || null,
      last_known_good_protocol_version: integerOrNull(value.last_known_good_protocol_version),
      last_known_good_product_scope: value.last_known_good_product_scope || null,
      pending_version: value.pending_version || null,
      pending_protocol_version: integerOrNull(value.pending_protocol_version),
      pending_product_scope: value.pending_product_scope || null,
      protocol_floor: integerOrNull(value.protocol_floor) ?? 0,
      pi_only_established_at: value.pi_only_established_at || null,
      legacy_baseline_confirmed_at: value.legacy_baseline_confirmed_at || null,
      legacy_fallback_consumed: Boolean(value.legacy_fallback_consumed),
      legacy_fallback_attempted_at: value.legacy_fallback_attempted_at || null,
      legacy_fallback_completed_at: value.legacy_fallback_completed_at || null,
      legacy_fallback_version: value.legacy_fallback_version || null,
      legacy_fallback_from: value.legacy_fallback_from || null,
      last_error: value.last_error || null,
      updated_at: value.updated_at || new Date().toISOString(),
    };
  }

  function nextSuccessfulInstallState(value, manifest, {
    emergencyLegacyFallback = false,
    timestamp = new Date().toISOString(),
  } = {}) {
    const state = normalizeInstallState(value);
    const protocolVersion = integerOrNull(manifest?.protocol_version);
    const bridgeVersion = String(manifest?.bridge_version || "");
    const productScope = manifest?.product_scope || null;
    if (!bridgeVersion || protocolVersion === null) {
      throw new BundleError("bundle_launch_state_invalid", "Successful Bridge launch metadata is invalid");
    }
    if (protocolVersion === PROTOCOL_VERSION && productScope === PRODUCT_SCOPE) {
      return {
        ...state,
        current_version: bridgeVersion,
        current_protocol_version: protocolVersion,
        current_product_scope: productScope,
        last_known_good: bridgeVersion,
        last_known_good_protocol_version: protocolVersion,
        last_known_good_product_scope: productScope,
        pending_version: null,
        pending_protocol_version: null,
        pending_product_scope: null,
        protocol_floor: Math.max(state.protocol_floor, PROTOCOL_VERSION),
        pi_only_established_at: state.pi_only_established_at || timestamp,
        legacy_fallback_consumed: true,
        last_error: null,
        updated_at: timestamp,
      };
    }
    if (
      protocolVersion === 1
      && !emergencyLegacyFallback
      && bridgeVersion === LEGACY_BUNDLED_BASELINE_VERSION
      && state.protocol_floor < PROTOCOL_VERSION
      && !state.legacy_fallback_consumed
    ) {
      return {
        ...state,
        current_version: bridgeVersion,
        current_protocol_version: protocolVersion,
        current_product_scope: null,
        last_known_good: bridgeVersion,
        last_known_good_protocol_version: protocolVersion,
        last_known_good_product_scope: null,
        pending_version: null,
        pending_protocol_version: null,
        pending_product_scope: null,
        legacy_baseline_confirmed_at: state.legacy_baseline_confirmed_at || timestamp,
        last_error: null,
        updated_at: timestamp,
      };
    }
    if (protocolVersion === 1 && emergencyLegacyFallback) {
      const reserved = (
        state.legacy_fallback_consumed
        && state.legacy_fallback_attempted_at
        && !state.legacy_fallback_completed_at
        && state.legacy_fallback_version === bridgeVersion
      );
      if (state.protocol_floor >= PROTOCOL_VERSION || !reserved) {
        throw new BundleError("bundle_legacy_fallback_blocked", "Legacy Bridge fallback is no longer permitted");
      }
      return {
        ...state,
        current_version: bridgeVersion,
        current_protocol_version: protocolVersion,
        current_product_scope: null,
        last_known_good: bridgeVersion,
        last_known_good_protocol_version: protocolVersion,
        last_known_good_product_scope: null,
        pending_version: null,
        pending_protocol_version: null,
        pending_product_scope: null,
        legacy_fallback_consumed: true,
        legacy_fallback_completed_at: timestamp,
        updated_at: timestamp,
      };
    }
    throw new BundleError("bundle_launch_protocol_unsupported", "Bridge launch cannot establish a supported install state");
  }

  function rollbackDecision(value, candidateManifest, failedManifest) {
    const state = normalizeInstallState(value);
    const candidateProtocol = integerOrNull(candidateManifest?.protocol_version);
    const failedProtocol = integerOrNull(failedManifest?.protocol_version);
    if (candidateProtocol === null || failedProtocol === null) {
      return { allowed: false, emergencyLegacyFallback: false, reason: "protocol_missing" };
    }
    if (candidateProtocol < state.protocol_floor) {
      return { allowed: false, emergencyLegacyFallback: false, reason: "protocol_floor" };
    }
    if (candidateProtocol === 1) {
      if (candidateManifest.bridge_version !== LEGACY_BUNDLED_BASELINE_VERSION) {
        return { allowed: false, emergencyLegacyFallback: false, reason: "legacy_baseline_version" };
      }
      if (failedProtocol < PROTOCOL_VERSION) {
        return { allowed: false, emergencyLegacyFallback: false, reason: "not_a_v2_upgrade" };
      }
      if (state.protocol_floor >= PROTOCOL_VERSION) {
        return { allowed: false, emergencyLegacyFallback: false, reason: "pi_only_established" };
      }
      if (state.legacy_fallback_consumed) {
        return { allowed: false, emergencyLegacyFallback: false, reason: "legacy_fallback_consumed" };
      }
      return { allowed: true, emergencyLegacyFallback: true, reason: "first_v2_upgrade" };
    }
    if (candidateProtocol === PROTOCOL_VERSION && candidateManifest.product_scope === PRODUCT_SCOPE) {
      return { allowed: true, emergencyLegacyFallback: false, reason: "pi_only_rollback" };
    }
    return { allowed: false, emergencyLegacyFallback: false, reason: "candidate_incompatible" };
  }

  function reserveLegacyFallbackState(value, candidateManifest, failedManifest, {
    timestamp = new Date().toISOString(),
  } = {}) {
    const state = normalizeInstallState(value);
    const decision = rollbackDecision(state, candidateManifest, failedManifest);
    if (!decision.allowed || !decision.emergencyLegacyFallback) {
      throw new BundleError("bundle_legacy_fallback_blocked", "Legacy Bridge fallback cannot be reserved", {
        reason: decision.reason,
      });
    }
    return {
      ...state,
      legacy_fallback_consumed: true,
      legacy_fallback_attempted_at: timestamp,
      legacy_fallback_completed_at: null,
      legacy_fallback_version: candidateManifest.bridge_version,
      legacy_fallback_from: failedManifest.bridge_version,
      updated_at: timestamp,
    };
  }

  function pathInside(root, candidate, PathUtils) {
    const normalizedRoot = PathUtils.normalize(root).replace(/[\\/]+$/, "");
    const normalizedCandidate = PathUtils.normalize(candidate);
    const rootLower = normalizedRoot.toLowerCase();
    const candidateLower = normalizedCandidate.toLowerCase();
    return candidateLower === rootLower || candidateLower.startsWith(`${rootLower}\\`) || candidateLower.startsWith(`${rootLower}/`);
  }

  function bytesToHex(binary) {
    let result = "";
    for (let index = 0; index < binary.length; index += 1) {
      result += binary.charCodeAt(index).toString(16).padStart(2, "0");
    }
    return result;
  }

  function create(options) {
    const { rootURI, addonVersion, Services, IOUtils, PathUtils, Zotero, appendLog } = options;
    const Ci = Components.interfaces;
    const Cc = Components.classes;

    function delay(milliseconds) {
      return new Promise((resolve) => setTimeout(resolve, milliseconds));
    }

    function binaryRoot() {
      try {
        const localAppData = Services.dirsvc.get("LocalAppData", Ci.nsIFile).path;
        return PathUtils.join(localAppData, "ZoteroAgentBridge", "bridge");
      } catch (error) {
        return PathUtils.join(PathUtils.profileDir, "zotero-agent-bridge-binaries");
      }
    }

    function managedPath(root, ...parts) {
      const candidate = PathUtils.join(root, ...parts);
      if (!pathInside(root, candidate, PathUtils)) {
        throw new BundleError("bundle_path_escape", `Managed path escapes Bundle root: ${candidate}`);
      }
      return candidate;
    }

    async function readManifest() {
      const raw = Zotero.File.getContentsFromURL(`${rootURI}${BUNDLE_PREFIX}bridge-manifest.json`);
      const manifest = validateBundledManifest(JSON.parse(raw), addonVersion);
      if (manifest.bridge_version !== addonVersion) {
        throw new BundleError("bundle_version_mismatch", "Add-on and Bridge Bundle versions do not match", {
          addon_version: addonVersion,
          bridge_version: manifest.bridge_version,
        });
      }
      return { manifest, raw };
    }

    function hashBytes(bytes) {
      const hash = Cc["@mozilla.org/security/hash;1"].createInstance(Ci.nsICryptoHash);
      hash.init(hash.SHA256);
      hash.update(bytes, bytes.length);
      return bytesToHex(hash.finish(false));
    }

    function hashText(text) {
      return hashBytes(new TextEncoder().encode(text));
    }

    function localFile(path) {
      const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
      file.initWithPath(path);
      return file;
    }

    async function hashFile(path) {
      return hashBytes(await IOUtils.read(path));
    }

    function sourceArchive() {
      const uri = Services.io.newURI(rootURI);
      if (uri.scheme === "jar") {
        const jar = uri.QueryInterface(Ci.nsIJARURI);
        return { kind: "zip", file: jar.JARFile.QueryInterface(Ci.nsIFileURL).file };
      }
      if (uri.scheme === "file") {
        return { kind: "directory", file: uri.QueryInterface(Ci.nsIFileURL).file };
      }
      throw new BundleError("bundle_source_unsupported", `Unsupported add-on URI: ${rootURI}`);
    }

    async function acquireLock(root) {
      await IOUtils.makeDirectory(root, { ignoreExisting: true });
      const lockPath = managedPath(root, INSTALL_LOCK);
      const deadline = Date.now() + LOCK_WAIT_MS;
      while (Date.now() < deadline) {
        try {
          const file = localFile(lockPath);
          file.create(Ci.nsIFile.NORMAL_FILE_TYPE, 0o600);
          await IOUtils.writeUTF8(lockPath, JSON.stringify({ pid: Services.appinfo.processID, acquired_at: new Date().toISOString() }));
          return async () => {
            try {
              await IOUtils.remove(lockPath, { ignoreAbsent: true });
            } catch (error) {}
          };
        } catch (error) {
          try {
            const stat = await IOUtils.stat(lockPath);
            if (Date.now() - stat.lastModified > LOCK_STALE_MS) {
              await IOUtils.remove(lockPath, { ignoreAbsent: true });
              continue;
            }
          } catch (statError) {}
          await delay(100);
        }
      }
      throw new BundleError("bundle_install_locked", "Timed out waiting for the Bridge Bundle installation lock");
    }

    async function extractFile(source, archivePath, destination) {
      await IOUtils.makeDirectory(PathUtils.parent(destination), { ignoreExisting: true });
      if (source.kind === "zip") {
        const reader = Cc["@mozilla.org/libjar/zip-reader;1"].createInstance(Ci.nsIZipReader);
        reader.open(source.file);
        try {
          const entry = `${BUNDLE_PREFIX}${archivePath}`;
          if (!reader.hasEntry(entry)) {
            throw new BundleError("bundle_file_missing", `XPI Bundle entry is missing: ${entry}`);
          }
          const zipEntry = reader.getEntry(entry);
          if (zipEntry.isDirectory || zipEntry.isSynthetic) {
            throw new BundleError("bundle_file_invalid", `XPI Bundle entry is not a regular file: ${entry}`);
          }
          reader.extract(entry, localFile(destination));
        } finally {
          reader.close();
        }
        return;
      }
      const sourcePath = PathUtils.join(source.file.path, ...BUNDLE_PREFIX.split("/").filter(Boolean), ...archivePath.split("/"));
      await IOUtils.copy(sourcePath, destination, { noOverwrite: true });
    }

    async function verifyFiles(root, manifest) {
      for (const record of manifest.files) {
        const path = managedPath(root, ...record.path.split("/"));
        const stat = await IOUtils.stat(path);
        if (stat.type !== "regular" || stat.size !== record.size) {
          throw new BundleError("bundle_file_size_mismatch", `Bridge Bundle file size mismatch: ${record.path}`);
        }
        const digest = await hashFile(path);
        if (digest !== record.sha256) {
          throw new BundleError("bundle_file_hash_mismatch", `Bridge Bundle file hash mismatch: ${record.path}`);
        }
      }
      const entrypoint = managedPath(root, ...manifest.entrypoint.split("/"));
      if (!(await IOUtils.exists(entrypoint)) || !pathInside(root, entrypoint, PathUtils)) {
        throw new BundleError("bundle_entrypoint_invalid", "Bridge Bundle entrypoint is missing or unsafe");
      }
      return entrypoint;
    }

    async function validateInstalled(versionRoot, manifest, manifestSha256) {
      const sentinelPath = managedPath(versionRoot, manifest.sentinel);
      if (!(await IOUtils.exists(sentinelPath))) {
        return null;
      }
      const sentinel = JSON.parse(await IOUtils.readUTF8(sentinelPath));
      if (
        sentinel.sentinel_schema_version !== 1
        || sentinel.bridge_version !== manifest.bridge_version
        || sentinel.protocol_version !== manifest.protocol_version
        || sentinel.product_scope !== manifest.product_scope
        || sentinel.manifest_sha256 !== manifestSha256
        || sentinel.entrypoint !== manifest.entrypoint
      ) {
        return null;
      }
      return verifyFiles(versionRoot, manifest);
    }

    async function writeAtomic(path, payload) {
      const temporary = `${path}.tmp-${Services.uuid.generateUUID().toString().replace(/[{}-]/g, "")}`;
      await IOUtils.writeUTF8(temporary, JSON.stringify(payload, null, 2));
      await IOUtils.move(temporary, path, { noOverwrite: false });
    }

    async function readInstallState(root) {
      const path = managedPath(root, INSTALL_STATE);
      if (!(await IOUtils.exists(path))) {
        return normalizeInstallState();
      }
      return normalizeInstallState(JSON.parse(await IOUtils.readUTF8(path)));
    }

    async function validateStoredVersion(root, version, { allowLegacyProtocol = false } = {}) {
      if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(String(version || ""))) {
        return null;
      }
      const versionRoot = managedPath(root, String(version));
      const storedManifestPath = managedPath(versionRoot, ".zab-bundle-manifest.json");
      if (!(await IOUtils.exists(storedManifestPath))) {
        return null;
      }
      try {
        const raw = await IOUtils.readUTF8(storedManifestPath);
        const parsed = JSON.parse(raw);
        const manifest = parsed.protocol_version === PROTOCOL_VERSION
          ? validateManifest(parsed)
          : (
              allowLegacyProtocol
              && parsed.protocol_version === 1
              && parsed.bridge_version === LEGACY_BUNDLED_BASELINE_VERSION
                ? validateLegacyManifest(parsed)
                : null
            );
        if (!manifest || manifest.bridge_version !== version) {
          return null;
        }
        const manifestSha256 = hashText(raw);
        const executable = await validateInstalled(versionRoot, manifest, manifestSha256);
        return executable ? {
          root,
          versionRoot,
          executable,
          manifest,
          manifestSha256,
          reused: true,
          rollback: true,
          legacyProtocol: manifest.protocol_version === 1,
        } : null;
      } catch (error) {
        return null;
      }
    }

    async function markLaunchSucceeded(bundleInfo, { emergencyLegacyFallback = false } = {}) {
      const root = bundleInfo.root;
      const release = await acquireLock(root);
      try {
        const state = await readInstallState(root);
        await writeAtomic(
          managedPath(root, INSTALL_STATE),
          nextSuccessfulInstallState(state, bundleInfo.manifest, { emergencyLegacyFallback }),
        );
      } finally {
        await release();
      }
    }

    async function recordLaunchFailure(bundleInfo, error) {
      const root = bundleInfo.root;
      const release = await acquireLock(root);
      try {
        const state = await readInstallState(root);
        await writeAtomic(managedPath(root, INSTALL_STATE), {
          ...state,
          state_schema_version: 1,
          pending_version: null,
          pending_protocol_version: null,
          pending_product_scope: null,
          last_error: {
            bridge_version: bundleInfo.manifest.bridge_version,
            protocol_version: bundleInfo.manifest.protocol_version,
            product_scope: bundleInfo.manifest.product_scope || null,
            code: error?.code || "bridge_start_failed",
            message: error?.message || String(error),
            recorded_at: new Date().toISOString(),
          },
          updated_at: new Date().toISOString(),
        });
      } finally {
        await release();
      }
    }

    async function rollbackCandidate(failedBundleInfo) {
      const root = binaryRoot();
      const release = await acquireLock(root);
      try {
        const state = await readInstallState(root);
        const failedManifest = failedBundleInfo?.manifest || failedBundleInfo || {};
        const failedVersion = String(failedManifest.bridge_version || "");
        if (!state.last_known_good || state.last_known_good === failedVersion) {
          return null;
        }
        const allowLegacyProtocol = (
          state.protocol_floor < PROTOCOL_VERSION
          && !state.legacy_fallback_consumed
          && Number(failedManifest.protocol_version) >= PROTOCOL_VERSION
        );
        const candidate = await validateStoredVersion(root, state.last_known_good, { allowLegacyProtocol });
        if (!candidate) {
          return null;
        }
        const decision = rollbackDecision(state, candidate.manifest, failedManifest);
        if (!decision.allowed) {
          await appendLog("warn", "bridge_bundle_rollback_rejected", {
            failed_version: failedVersion,
            rollback_version: candidate.manifest.bridge_version,
            rollback_protocol_version: candidate.manifest.protocol_version,
            protocol_floor: state.protocol_floor,
            reason: decision.reason,
          });
          return null;
        }
        if (decision.emergencyLegacyFallback) {
          const reservedState = reserveLegacyFallbackState(state, candidate.manifest, failedManifest);
          await writeAtomic(managedPath(root, INSTALL_STATE), reservedState);
          await appendLog("warn", "bridge_legacy_fallback_reserved", {
            failed_version: failedVersion,
            rollback_version: candidate.manifest.bridge_version,
            attempted_at: reservedState.legacy_fallback_attempted_at,
          });
        }
        return { ...candidate, emergencyLegacyFallback: decision.emergencyLegacyFallback };
      } finally {
        await release();
      }
    }

    async function ensureInstalled() {
      const root = binaryRoot();
      const release = await acquireLock(root);
      try {
        const { manifest, raw } = await readManifest();
        const manifestSha256 = hashText(raw);
        const versionRoot = managedPath(root, manifest.bridge_version);
        if (await IOUtils.exists(versionRoot)) {
          const existingEntrypoint = await validateInstalled(versionRoot, manifest, manifestSha256);
          if (existingEntrypoint) {
            const state = await readInstallState(root);
            if (
              state.last_known_good !== manifest.bridge_version
              || state.last_known_good_protocol_version !== manifest.protocol_version
              || state.pending_version !== manifest.bridge_version
              || state.pending_protocol_version !== manifest.protocol_version
            ) {
              await writeAtomic(managedPath(root, INSTALL_STATE), {
                ...state,
                state_schema_version: 1,
                current_version: manifest.bridge_version,
                current_protocol_version: manifest.protocol_version,
                current_product_scope: manifest.product_scope,
                pending_version: manifest.bridge_version,
                pending_protocol_version: manifest.protocol_version,
                pending_product_scope: manifest.product_scope,
                updated_at: new Date().toISOString(),
              });
            }
            return { root, versionRoot, executable: existingEntrypoint, manifest, manifestSha256, reused: true };
          }
          const quarantineName = `${manifest.bridge_version}.invalid-${Services.uuid.generateUUID().toString().replace(/[{}-]/g, "")}`;
          try {
            await IOUtils.move(versionRoot, managedPath(root, quarantineName), { noOverwrite: true });
          } catch (error) {
            throw new BundleError(
              "bundle_existing_invalid",
              `Existing Bridge Bundle directory is invalid and could not be quarantined: ${versionRoot}`,
              { cause: error && error.message ? error.message : String(error) },
            );
          }
          await appendLog("warn", "bridge_bundle_existing_quarantined", {
            bridge_version: manifest.bridge_version,
            quarantined_to: quarantineName,
          });
        }

        const stagingName = `.staging-${Services.uuid.generateUUID().toString().replace(/[{}-]/g, "")}`;
        const stagingRoot = managedPath(root, stagingName);
        await IOUtils.makeDirectory(stagingRoot, { ignoreExisting: false });
        const source = sourceArchive();
        for (const record of manifest.files) {
          const destination = managedPath(stagingRoot, ...record.path.split("/"));
          await extractFile(source, record.path, destination);
          const stat = await IOUtils.stat(destination);
          if (stat.type !== "regular" || stat.size !== record.size || await hashFile(destination) !== record.sha256) {
            throw new BundleError("bundle_extract_verification_failed", `Extracted Bridge file failed verification: ${record.path}`);
          }
        }
        const executable = await verifyFiles(stagingRoot, manifest);
        await IOUtils.writeUTF8(managedPath(stagingRoot, ".zab-bundle-manifest.json"), raw);
        await IOUtils.writeUTF8(
          managedPath(stagingRoot, manifest.sentinel),
          JSON.stringify({
            sentinel_schema_version: 1,
            bridge_version: manifest.bridge_version,
            protocol_version: manifest.protocol_version,
            product_scope: manifest.product_scope,
            manifest_sha256: manifestSha256,
            installed_at: new Date().toISOString(),
            entrypoint: manifest.entrypoint,
          }, null, 2),
        );
        await IOUtils.move(stagingRoot, versionRoot, { noOverwrite: true });
        const installedExecutable = managedPath(versionRoot, ...manifest.entrypoint.split("/"));
        const previousState = await readInstallState(root);
        await writeAtomic(managedPath(root, INSTALL_STATE), {
          ...previousState,
          state_schema_version: 1,
          current_version: manifest.bridge_version,
          current_protocol_version: manifest.protocol_version,
          current_product_scope: manifest.product_scope,
          pending_version: manifest.bridge_version,
          pending_protocol_version: manifest.protocol_version,
          pending_product_scope: manifest.product_scope,
          updated_at: new Date().toISOString(),
        });
        await appendLog("info", "bridge_bundle_installed", {
          bridge_version: manifest.bridge_version,
          files: manifest.files.length,
          binary_root: root,
        });
        return { root, versionRoot, executable: installedExecutable, manifest, manifestSha256, reused: false };
      } finally {
        await release();
      }
    }

    return {
      binaryRoot,
      ensureInstalled,
      markLaunchSucceeded,
      recordLaunchFailure,
      rollbackCandidate,
    };
  }

  return {
    create,
    BundleError,
    __test: {
      normalizeManifestPath,
      pathInside,
      validateManifest,
      validateLegacyManifest,
      validateBundledManifest,
      normalizeInstallState,
      nextSuccessfulInstallState,
      rollbackDecision,
      reserveLegacyFallbackState,
      PROTOCOL_VERSION,
      PRODUCT_SCOPE,
      LEGACY_BUNDLED_BASELINE_VERSION,
    },
  };
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = ZoteroAgentBridgeBundleManager;
}
