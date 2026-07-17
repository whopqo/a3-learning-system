"""
启动器 -- 双击运行即可打开 AI 学习助手
"""
import subprocess, webbrowser, threading, os, sys, time, urllib.request

os.chdir(os.path.dirname(os.path.abspath(__file__)))
server = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")

print("=" * 50)
print("  AI 个性化学习助手 -- 多智能体系统")
print("  第十五届中国软件杯大赛 - A组赛题")
print("=" * 50)
print()
print("正在启动服务...")
print("浏览器稍后会自动打开 http://localhost:8000")
print("按 Ctrl+C 可以停止服务")
print()


def open_browser():
    """轮询健康检查，服务就绪后打开浏览器"""
    url = "http://localhost:8000/api/health"
    for _ in range(60):  # 最多等60秒
        time.sleep(1)
        try:
            urllib.request.urlopen(url, timeout=2)
            webbrowser.open("http://localhost:8000")
            return
        except Exception:
            pass
    print("\n服务启动超时，请手动打开 http://localhost:8000")


threading.Thread(target=open_browser, daemon=True).start()

p = subprocess.Popen([sys.executable, server])
try:
    p.wait()
except KeyboardInterrupt:
    print("\n正在停止...")
    p.terminate()
    p.wait()
    print("已停止。")
