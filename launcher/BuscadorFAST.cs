// Abre o BuscadorFAST: liga o servidor local sem janela de console e abre a tela no navegador.
// Se o programa já estiver aberto, só abre a tela de novo.
// Compilar: launcher\compilar.bat
using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("BuscadorFAST")]
[assembly: System.Reflection.AssemblyProduct("BuscadorFAST")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

static class Program
{
    const string Url = "http://127.0.0.1:8765";

    [STAThread]
    static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        if (Alive())
        {
            OpenBrowser();
            return;
        }

        string pythonw = Path.Combine(dir, @".venv\Scripts\pythonw.exe");
        if (!File.Exists(pythonw))
        {
            MessageBox.Show("Não encontrei o ambiente do programa em:\n" + pythonw +
                            "\n\nO BuscadorFAST.exe precisa ficar na pasta do BuscadorFAST.",
                            "BuscadorFAST", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        var psi = new ProcessStartInfo(pythonw, "-m buscador abrir --sem-navegador")
        {
            WorkingDirectory = dir,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        Process server = Process.Start(psi);

        // espera o servidor responder (até 60 s) antes de abrir a tela
        for (int i = 0; i < 120; i++)
        {
            if (Alive())
            {
                OpenBrowser();
                return;
            }
            if (server.HasExited) break;
            Thread.Sleep(500);
        }
        MessageBox.Show("O BuscadorFAST não conseguiu iniciar.\nVeja o arquivo data\\servidor.log para os detalhes.",
                        "BuscadorFAST", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }

    static bool Alive()
    {
        try
        {
            var req = (HttpWebRequest)WebRequest.Create(Url + "/api/jobs");
            req.Timeout = 1500;
            req.Proxy = null;
            using (req.GetResponse()) { }
            return true;
        }
        catch
        {
            return false;
        }
    }

    static void OpenBrowser()
    {
        Process.Start(new ProcessStartInfo(Url) { UseShellExecute = true });
    }
}
