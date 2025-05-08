from flask import Flask, render_template, request, make_response, jsonify
from zabbix_api import ZabbixAPI
from zabbix_connection import get_zabbix
from network_interfaces import get_hosts, get_network_interfaces
import matplotlib.pyplot as plt
from io import BytesIO
import base64
import time
from datetime import datetime
import numpy as np
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch
from matplotlib.ticker import FuncFormatter
import plotly.graph_objects as go
import logging
import traceback

app = Flask(__name__)

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tipos de histórico válidos
VALID_HISTORY_TYPES = {
    0: 'float',
    1: 'string', 
    2: 'log',
    3: 'integer',
    4: 'text'
}

@app.route('/api/hosts', methods=['GET'])
def api_get_hosts():
    try:
        zapi = get_zabbix()
        hosts = get_hosts(zapi)
        return jsonify(hosts)
    except Exception as e:
        logger.error(f"Error in api_get_hosts: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/interfaces', methods=['GET'])
def api_get_interfaces():
    try:
        hostid = request.args.get('hostid')
        if not hostid:
            return jsonify({'error': 'hostid é obrigatório'}), 400

        zapi = get_zabbix()
        interfaces = get_network_interfaces(zapi, hostid)
        return jsonify(interfaces)
    except Exception as e:
        logger.error(f"Error in api_get_interfaces: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

def format_speed(value, pos=None):
    """Formatador para converter valores de velocidade"""
    if value >= 1000000:  # Gbps
        return f"{value/1000000:.1f} Gbps"
    elif value >= 1000:  # Mbps
        return f"{value/1000:.1f} Mbps"
    else:  # Kbps
        return f"{value:.1f} Kbps"

def create_gauge(value, title, max_value):
    """Cria um gráfico de gauge usando Plotly"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(value, 2),
        number={'valueformat': '.2f'},
        title={'text': title},
        gauge={
            'axis': {'range': [0, max_value]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, max_value*0.6], 'color': "lightgray"},
                {'range': [max_value*0.6, max_value*0.8], 'color': "gray"},
                {'range': [max_value*0.8, max_value], 'color': "darkgray"}
            ],
        }
    ))
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig

def calculate_percentile(data, percentile=95):
    """Calcula o percentil dos dados"""
    if not data:
        return 0
    values = [d['value'] for d in data]
    return np.percentile(values, percentile)

@app.route('/', methods=['GET'])
def index():
    try:
        zapi = get_zabbix()
        
        groups = zapi.do_request('hostgroup.get', {
            "output": ["groupid", "name"],
            "sortfield": "name",
            "with_monitored_hosts": True,
            "with_hosts": True
        })['result']
        
        hosts = zapi.do_request('host.get', {
            "output": ["hostid", "name"],
            "filter": {"status": "0"},
            "monitored_hosts": True,
            "selectGroups": ["groupid", "name"],
            "preservekeys": True
        })['result']
        
        return render_template('index.html', 
                           hosts=list(hosts.values()),
                           groups=groups)
    
    except Exception as e:
        logger.error(f"Error in index: {str(e)}\n{traceback.format_exc()}")
        return render_template('error.html', error=str(e))

@app.route('/report', methods=['POST'])
def generate_report():
    try:
        hostid = request.form['host']
        interface = request.form.get('interface', '')
        period = int(request.form.get('period', 15))

        zapi = get_zabbix()

        # Obtém informações do host (correção aqui)
        host_info = zapi.do_request('host.get', {
            "output": ["hostid", "name"],
            "hostids": hostid,
            "selectGroups": ["groupid", "name"]
        })['result']

        if not host_info:
            return render_template('error.html', error="Host não encontrado"), 404

        host_info = host_info[0]  # Pega o primeiro host (deveria ser único pelo hostid)

        # Obtém o nome do grupo (assumindo que o host pertence a apenas um grupo)
        group_name = host_info['groups'][0]['name'] if host_info.get('groups') else 'Nenhum grupo'
        
        # Obtém itens de interface
        items = zapi.do_request('item.get', {
            "output": ["itemid", "name", "key_", "value_type"],
            "hostids": hostid,
            "search": {"key_": "net.if"},
            "filter": {"status": 0},
            "limit": 50
        })['result']

        # Filtra itens para a interface específica
        filtered_items = []
        for item in items:
            if (interface in item['key_'] or 
                interface in item['name'] or
                any(interface in part for part in item['key_'].split('['))):
                filtered_items.append(item)

        if not filtered_items:
            return render_template('error.html', 
                                error=f"Nenhum item encontrado para a interface {interface}"), 400

        # Obtém dados históricos
        time_till = int(time.time())
        time_from = time_till - (period * 60)
        
        data = {"download": [], "upload": []}
        
        for item in filtered_items:
            try:
                history = zapi.do_request('history.get', {
                    "output": ["clock", "value"],
                    "itemids": item['itemid'],
                    "time_from": time_from,
                    "time_till": time_till,
                    "sortfield": "clock",
                    "sortorder": "ASC",
                    "history": int(item['value_type']),
                    "limit": 1000
                })['result']

                values = []
                for point in history:
                    timestamp = datetime.fromtimestamp(int(point['clock']))
                    value = (float(point['value']) * 8) / 1000  # Converter bytes para bits e depois para kbps
                    values.append({
                        "timestamp": timestamp,
                        "value": value,
                        "formatted_value": format_speed(value)
                    })

                if "net.if.in" in item['key_'] or "InOctets" in item['key_']:
                    data["download"] = values
                elif "net.if.out" in item['key_'] or "OutOctets" in item['key_']:
                    data["upload"] = values

            except Exception as e:
                logger.error(f"Error processing item {item['itemid']}: {str(e)}")
                continue

        # Verifica se há dados
        if not data["download"] and not data["upload"]:
            return render_template('error.html', 
                                error="Nenhum dado histórico encontrado"), 400

        # Calcula percentis
        percentile_data = {
            "download": calculate_percentile(data["download"]) if data["download"] else 0,
            "upload": calculate_percentile(data["upload"]) if data["upload"] else 0
        }

        # Geração de gráficos (código existente)
        plt.figure(figsize=(12, 6))
        
        if data["download"]:
            timestamps = [point["timestamp"] for point in data["download"]]
            values = [point["value"] for point in data["download"]]
            plt.plot(timestamps, values, label='Download', color='blue')
        
        if data["upload"]:
            timestamps = [point["timestamp"] for point in data["upload"]]
            values = [point["value"] for point in data["upload"]]
            plt.plot(timestamps, values, label='Upload', color='red')
        
        plt.title(f"Tráfego da Interface {interface} - Últimos {period} minutos")
        plt.ylabel("Velocidade (kbps)")
        plt.gca().yaxis.set_major_formatter(FuncFormatter(format_speed))
        
        if data["download"]:
            plt.gca().xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M'))
            plt.gca().text(0.01, 0.01, timestamps[0].strftime('%Y-%m-%d'), 
                         transform=plt.gca().transAxes, fontsize=8)
            plt.gca().text(0.9, 0.01, timestamps[-1].strftime('%Y-%m-%d'), 
                         transform=plt.gca().transAxes, fontsize=8, ha='right')
        
        plt.xticks(rotation=45)
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        
        # Salva gráfico principal
        main_graph_buffer = BytesIO()
        plt.savefig(main_graph_buffer, format='png', dpi=100, bbox_inches='tight')
        plt.close()
        main_graph_buffer.seek(0)
        main_graph_base64 = base64.b64encode(main_graph_buffer.getvalue()).decode('utf-8')
        
        # Gera gráficos de gauge
        max_speed = max(
            max([d['value'] for d in data["download"]], default=0),
            max([u['value'] for u in data["upload"]], default=0)
        ) * 1.2
        
        # Gauge para download
        last_download = data["download"][-1]['value'] if data["download"] else 0
        gauge_download = create_gauge(last_download, "Último Download", max_speed)
        gauge_download_buffer = BytesIO()
        gauge_download.write_image(gauge_download_buffer, format='png')
        gauge_download_base64 = base64.b64encode(gauge_download_buffer.getvalue()).decode('utf-8')
        
        # Gauge para upload
        last_upload = data["upload"][-1]['value'] if data["upload"] else 0
        gauge_upload = create_gauge(last_upload, "Último Upload", max_speed)
        gauge_upload_buffer = BytesIO()
        gauge_upload.write_image(gauge_upload_buffer, format='png')
        gauge_upload_base64 = base64.b64encode(gauge_upload_buffer.getvalue()).decode('utf-8')
        
        # Gauge para percentil
        gauge_percentile = create_gauge(percentile_data["download"], "95th Percentil Download", max_speed)
        gauge_percentile_buffer = BytesIO()
        gauge_percentile.write_image(gauge_percentile_buffer, format='png')
        gauge_percentile_base64 = base64.b64encode(gauge_percentile_buffer.getvalue()).decode('utf-8')
        
        # Verifica se é requisição de PDF
        if request.form.get('generate_pdf'):
            return generate_pdf_response(
                period, 
                main_graph_base64, 
                data, 
                gauge_download_base64,
                gauge_upload_base64,
                gauge_percentile_base64,
                percentile_data,
                interface
            )
        
        return render_template('report.html',
                     graph=main_graph_base64,
                     gauge_download=gauge_download_base64,
                     gauge_upload=gauge_upload_base64,
                     gauge_percentile=gauge_percentile_base64,
                     data=data,
                     period=period,
                     hostid=hostid,
                     interface=interface,
                     current_datetime=datetime.now(),
                     percentile=percentile_data,
                     host_name=host_info['name'],
                     group_name=group_name)
    
    except Exception as e:
        logger.error(f"Error in generate_report: {str(e)}")
        return render_template('error.html', error=str(e)), 500

def generate_pdf_response(period, main_graph, data, gauge_download, gauge_upload, gauge_percentile, percentile, interface):
    """Gera e retorna um PDF com os dados do relatório"""
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                              rightMargin=40, leftMargin=40,
                              topMargin=40, bottomMargin=40)

        styles = getSampleStyleSheet()
        elements = []
        
        # Título
        elements.append(Paragraph(f"Relatório de Tráfego - Interface {interface}", styles['Title']))
        elements.append(Spacer(1, 12))
        
        # Data e período
        elements.append(Paragraph(f"Período: últimos {period} minutos", styles['Normal']))
        elements.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles['Normal']))
        elements.append(Spacer(1, 24))
        
        # Gráfico principal
        img_data = base64.b64decode(main_graph)
        img = Image(BytesIO(img_data), width=6*inch, height=3*inch)
        elements.append(img)
        elements.append(Spacer(1, 24))
        
        # Gráficos de gauge
        elements.append(Paragraph("Indicadores de Desempenho", styles['Heading2']))
        elements.append(Spacer(1, 12))
        
        # Adiciona cada gauge individualmente
        elements.append(Image(BytesIO(base64.b64decode(gauge_download)), width=2.5*inch, height=2*inch))
        elements.append(Spacer(1, 12))
        elements.append(Image(BytesIO(base64.b64decode(gauge_upload)), width=2.5*inch, height=2*inch))
        elements.append(Spacer(1, 12))
        elements.append(Image(BytesIO(base64.b64decode(gauge_percentile)), width=2.5*inch, height=2*inch))
        elements.append(Spacer(1, 24))
        
        # Prepara os dados para a tabela
        max_download = max([d['value'] for d in data['download']]) if data['download'] else 0
        max_upload = max([u['value'] for u in data['upload']]) if data['upload'] else 0

        avg_download = sum([d['value'] for d in data['download']])/len(data['download']) if data['download'] else 0
        avg_upload = sum([u['value'] for u in data['upload']])/len(data['upload']) if data['upload'] else 0

        last_download = data['download'][-1]['value'] if data['download'] else 0
        last_upload = data['upload'][-1]['value'] if data['upload'] else 0

        tabela_dados = [
            ["Métrica", "Download", "Upload"],
            ["Máximo", format_speed(max_download), format_speed(max_upload)],
            ["Média", format_speed(avg_download), format_speed(avg_upload)],
            ["Último valor", format_speed(last_download), format_speed(last_upload)],
            ["95º Percentil", format_speed(percentile['download']), format_speed(percentile['upload'])]
        ]

        tabela = Table(tabela_dados, colWidths=[2*inch, 2*inch, 2*inch])
        tabela.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#D9E1F2")),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(tabela)
        elements.append(Spacer(1, 24))
        
        # Constrói o PDF
        doc.build(elements)
        
        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=relatorio_trafego_{interface}_{period}min.pdf'
        return response
        
    except Exception as e:
        logger.error(f"Error in generate_pdf_response: {str(e)}\n{traceback.format_exc()}")
        return render_template('error.html', error=str(e)), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

