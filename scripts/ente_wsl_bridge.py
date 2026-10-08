#!/usr/bin/env python3
"""WSL2 Port Forwarder for Ente Services.

Binds to external network interfaces (Wi-Fi 10.0.0.126 and NetBird 100.121.101.70)
and forwards TCP streams directly to the current WSL2 NAT address.
"""
import socket
import subprocess
import threading
import time

INTERFACES = ["10.0.0.126", "100.121.101.70"]
PORTS = [8085, 3005, 3002, 3200, 3201]


CREATE_NO_WINDOW = 0x08000000

def _run_wsl(cmd, **kwargs):
    si = None
    if hasattr(subprocess, "STARTUPINFO"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
    creationflags = kwargs.pop("creationflags", 0) | CREATE_NO_WINDOW
    return subprocess.run(cmd, startupinfo=si, creationflags=creationflags, **kwargs)
def get_wsl_ip():
    res = _run_wsl(
        ["wsl", "hostname", "-I"], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    out = res.stdout.strip() if res.stdout else ""
    if not out:
        raise RuntimeError("WSL did not return an IP address")
    return out.split()[0]
def pipe(src, dst):
    try:
        while True:
            data = src.recv(32768)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass

def handle_client(client_sock, target_port):
    backend = None
    try:
        target_ip = get_wsl_ip()
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.connect((target_ip, target_port))
        t1 = threading.Thread(target=pipe, args=(client_sock, backend), daemon=True)
        t2 = threading.Thread(target=pipe, args=(backend, client_sock), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        pass
    finally:
        try:
            client_sock.close()
        except Exception:
            pass
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass

def listen_on(ip, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((ip, port))
        server.listen(128)
        print(f"[ente_bridge] Listening on {ip}:{port} -> WSL:{port}", flush=True)
    except Exception as e:
        print(f"[ente_bridge] Failed to bind {ip}:{port} - {e}", flush=True)
        return

    while True:
        try:
            client, _ = server.accept()
            threading.Thread(target=handle_client, args=(client, port), daemon=True).start()
        except Exception:
            break


def ensure_web_patch():
    # Check and apply patch, then sleep for 10 minutes instead of every 10 seconds
    while True:
        try:
            res = _run_wsl(
                ["wsl", "-e", "docker", "exec", "ente-web-1", "grep", "-q", "let dx=()=>null", "/out/photos/_next/static/chunks/pages/gallery-67c645e5bc26acee.js"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            if res.returncode != 0:
                _run_wsl(
                    ["wsl", "-e", "docker", "cp", "/mnt/e/development/gallery-67c645e5bc26acee.js", "ente-web-1:/out/photos/_next/static/chunks/pages/gallery-67c645e5bc26acee.js"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception:
            pass
        time.sleep(600)
def main():
    threads = []
    for ip in INTERFACES:
        for port in PORTS:
            t = threading.Thread(target=listen_on, args=(ip, port), daemon=True)
            t.start()
            threads.append(t)

    threading.Thread(target=ensure_web_patch, daemon=True).start()
    print("[ente_bridge] All forwarders initialized.", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("[ente_bridge] Shutting down.", flush=True)

if __name__ == "__main__":
    main()
