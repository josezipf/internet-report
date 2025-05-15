# Internet Report - Integração com API do Zabbix

Este é um projeto educacional que permite a geração de relatórios a partir da API do Zabbix, utilizando Python. A aplicação foi desenvolvida com o apoio de Inteligência Artificial (IA), com o objetivo de auxiliar no aprendizado sobre automação, APIs e monitoramento de rede.

> **⚠️ Aviso Importante:**
>
> Este projeto foi desenvolvido com ajuda de Inteligência Artificial (IA) e **tem caráter exclusivamente educacional**.
>
> Ele **não foi testado quanto à segurança, desempenho ou uso em produção**.
>
> O código **NÃO deve ser utilizado em ambientes reais ou corporativos sem que o aluno avalie e adapte todos os pontos necessários** para segurança, performance e confiabilidade.
>
> **Use por sua conta e risco.** Adapte, revise e melhore o código conforme as necessidades do seu ambiente.

---

## ✅ Requisitos

- Python 3
- Git
- Zabbix (com acesso à API)
- Sistema Linux com `systemd`

---

## 🚀 Instalação

```bash
sudo apt update
sudo apt install python3-venv python3-pip git -y
```

Clone o repositório:

```bash
git clone https://github.com/josezipf/internet-report.git
cd internet-report
```

Crie e ative o ambiente virtual:

```bash
python3 -m venv venv
source venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

---

## 🔧 Configuração

Edite o arquivo `zabbix_connection.py` com os dados da sua instância Zabbix:

```python
ZABBIX_URL = "http://SEU_ZABBIX/zabbix"
ZABBIX_USER = "Admin"
ZABBIX_PASSWORD = "zabbix"
```

---

## ▶️ Execução

Você pode rodar a aplicação diretamente com:

```bash
python app.py
```

---

## ⚙️ Rodando como Serviço (Systemd)

Crie o arquivo de serviço:

```bash
sudo nano /etc/systemd/system/reportlink.service
```

Conteúdo do arquivo:

```ini
[Unit]
Description=Serviço Relatório de Links
After=network.target

[Service]
User=noto
WorkingDirectory=/home/noto/internet-report
ExecStart=/home/noto/internet-report/venv/bin/gunicorn -w 4 -b 0.0.0.0:5000 app:app
Environment="PATH=/home/noto/internet-report/venv/bin"
Restart=always

[Install]
WantedBy=multi-user.target
```

Ajuste permissões da pasta:

```bash
sudo chown -R noto:noto /home/noto/internet-report
```

Recarregue os serviços:

```bash
sudo systemctl daemon-reload
```

Inicie ou verifique o status do serviço:

```bash
service reportlink start
service reportlink status
```

---

## 📌 Observações Finais

- Este projeto é um exemplo prático de integração com a API do Zabbix.
- Ideal para fins de estudo, desenvolvimento de habilidades com Python, APIs e automação.
- O código pode ser reaproveitado, mas **não é recomendado o uso direto em produção** sem adaptações e testes adequados.

---

## 👨‍💻 Autor

Desenvolvido com apoio de IA e curadoria por [José Zipf](https://github.com/josezipf).

Repositório original: [github.com/josezipf/internet-report](https://github.com/josezipf/internet-report)

---

## 📜 Licença

Este projeto está sob a licença MIT. Consulte o arquivo `LICENSE` para mais detalhes.
