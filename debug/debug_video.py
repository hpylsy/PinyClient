"""
debug_video.py — 同时监听 UDP 0.0.0.0:3334，并以客户端身份连接 WebSocket 127.0.0.1:8765，
接收到任何数据包/帧时在控制台打印摘要信息。

用法:
    python debug_video.py
"""
import asyncio
import socket
import struct
import threading
import time

UDP_HOST = "0.0.0.0"
UDP_PORT = 3334
WS_URL   = "ws://127.0.0.1:8765"   # 连接到已有的视频服务，而非再开一个服务端

# ── 计数器（线程安全用 volatile int 近似即可，仅打印用途）──────────────────
_udp_pkt_count = 0
_ws_msg_count  = 0


# ══════════════════════════════════════════════════════════════════════════════
#  UDP 监听线程
# ══════════════════════════════════════════════════════════════════════════════
def _udp_thread() -> None:
    global _udp_pkt_count
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((UDP_HOST, UDP_PORT))
    except OSError as exc:
        print(f"[UDP] ❌ 绑定失败 {UDP_HOST}:{UDP_PORT}: {exc}")
        return
    print(f"[UDP] ✅ 监听 {UDP_HOST}:{UDP_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(65535)
        except Exception as exc:
            print(f"[UDP] ❌ 接收错误: {exc}")
            continue

        _udp_pkt_count += 1
        ts = time.strftime("%H:%M:%S")
        total_len = len(data)

        # 解析 8 字节头部（若长度足够）
        if total_len >= 9:
            frame_id  = struct.unpack_from(">H", data, 0)[0]
            slice_id  = struct.unpack_from(">H", data, 2)[0]
            frame_total = struct.unpack_from(">I", data, 4)[0]
            payload_len = total_len - 8
            print(
                f"[UDP #{_udp_pkt_count:>6}] {ts}  来源={addr[0]}:{addr[1]}"
                f"  frame={frame_id}  slice={slice_id}"
                f"  frame_total={frame_total}B  payload={payload_len}B"
            )
        else:
            print(
                f"[UDP #{_udp_pkt_count:>6}] {ts}  来源={addr[0]}:{addr[1]}"
                f"  长度={total_len}B  (包过短，无法解析头部)"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket 服务器（接收连接并打印收到的消息）
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket 客户端（连接到已有的视频服务，打印收到的帧）
# ══════════════════════════════════════════════════════════════════════════════
async def _ws_client() -> None:
    global _ws_msg_count
    try:
        import websockets
    except ImportError:
        print("[WS ] ❌ 未安装 websockets，跳过 WS 监听。运行: pip install websockets")
        return

    retry = 0
    while True:
        try:
            print(f"[WS ] 🔌 正在连接 {WS_URL} ...")
            async with websockets.connect(WS_URL) as ws:
                retry = 0
                print(f"[WS ] ✅ 已连接 {WS_URL}")
                async for msg in ws:
                    _ws_msg_count += 1
                    ts = time.strftime("%H:%M:%S")
                    if isinstance(msg, (bytes, bytearray)):
                        preview = msg[:16].hex(" ")
                        print(
                            f"[WS  #{_ws_msg_count:>6}] {ts}  binary  len={len(msg)}B"
                            f"  head=[{preview}]"
                        )
                    else:
                        preview = str(msg)[:120]
                        print(f"[WS  #{_ws_msg_count:>6}] {ts}  text    {preview}")
        except (OSError, Exception) as exc:
            retry += 1
            delay = min(1 * 2 ** retry, 16)
            print(f"[WS ] ⚠️  连接断开/失败: {exc}，{delay}s 后重试 (第{retry}次)")
            await asyncio.sleep(delay)


async def _async_main() -> None:
    await _ws_client()


# ══════════════════════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  PIONEER-client 视频链路调试工具")
    print(f"  UDP  监听 {UDP_HOST}:{UDP_PORT}  (绑定为服务端)")
    print(f"  WS   连接 {WS_URL}  (作为客户端观察)")
    print("  Ctrl+C 退出")
    print("=" * 60)

    # UDP 跑独立线程（阻塞式 recvfrom）
    t = threading.Thread(target=_udp_thread, daemon=True)
    t.start()

    # WebSocket 客户端跑 asyncio 循环（主线程）
    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        print("\n[SYS] 已退出")
