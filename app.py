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

# Registra a função como filtro Jinja2
def format_speed(value, pos=None):
    """Formatador inteligente para valores de rede"""
    value = float(value)
    
    if value == 0:
        return "0 bps"
    
    if value < 1000:  # Menos que 1 Kbps
        return f"{value:.2f} bps"
    
    if value < 1000000:  # Menos que 1 Mbps
        return f"{value/1000:.2f} Kbps"
    
    if value < 1000000000:  # Menos que 1 Gbps
        return f"{value/1000000:.2f} Mbps"
    
    return f"{value/1000000000:.2f} Gbps"

app.jinja_env.filters['format_speed'] = format_speed

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

        # Obtém informações do host
        host_info = zapi.do_request('host.get', {
            "output": ["hostid", "name"],
            "hostids": hostid,
            "selectGroups": ["groupid", "name"]
        })['result']

        if not host_info:
            return render_template('error.html', error="Host não encontrado"), 404

        host_info = host_info[0]
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
                    value = float(point['value'])  # Já está em bps
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

        if not data["download"] and not data["upload"]:
            return render_template('error.html', 
                                error="Nenhum dado histórico encontrado"), 400

        # Calcula percentis
        percentile_data = {
            "download": calculate_percentile(data["download"]) if data["download"] else 0,
            "upload": calculate_percentile(data["upload"]) if data["upload"] else 0,
            "download_formatted": format_speed(calculate_percentile(data["download"])) if data["download"] else "0 bps",
            "upload_formatted": format_speed(calculate_percentile(data["upload"])) if data["upload"] else "0 bps"
        }

        # Geração de gráficos
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
        plt.ylabel("Velocidade")
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

        # Verificação e cálculo do max_speed com tratamento de erro completo
        try:
            # Primeiro verifica se existem dados
            if not data["download"] and not data["upload"]:
                max_speed = 1000000  # Valor padrão se não houver dados
            else:
                # Calcula o máximo entre download e upload
                max_download = max([d['value'] for d in data["download"]]) if data["download"] else 0
                max_upload = max([u['value'] for u in data["upload"]]) if data["upload"] else 0
                max_speed = max(max_download, max_upload) * 1.2
        except (ValueError, KeyError) as e:
               logger.error(f"Error calculating max speed: {str(e)}")
               max_speed = 1000000  # 1 Mbps como fallback


        # Dados simplificados para exibição
        last_download = data["download"][-1]['formatted_value'] if data["download"] else "0 bps"
        last_upload = data["upload"][-1]['formatted_value'] if data["upload"] else "0 bps"
        last_download_time = data["download"][-1]['timestamp'].strftime('%H:%M') if data["download"] else ""
        last_upload_time = data["upload"][-1]['timestamp'].strftime('%H:%M') if data["upload"] else ""

        # Verifica se é requisição de PDF
        if request.form.get('generate_pdf'):
             return generate_pdf_response(
             period, 
             main_graph_base64, 
             data,
             percentile_data,
             interface,
             host_name=host_info['name'],
             group_name=group_name
        )

        return render_template('report.html',
             graph=main_graph_base64,
             data=data,
             period=period,
             hostid=hostid,
             interface=interface,
             current_datetime=datetime.now(),
             percentile=percentile_data,
             host_name=host_info['name'],
             group_name=group_name,
             last_download=last_download,
             last_upload=last_upload,
             last_download_time=last_download_time,
             last_upload_time=last_upload_time
        )

    except Exception as e:
        logger.error(f"Error in generate_report: {str(e)}")
        return render_template('error.html', error=str(e)), 500


def generate_pdf_response(period, main_graph, data, percentile, interface, host_name, group_name):
    if not all([host_name, group_name]):
        logger.error("Missing host or group information")
        return render_template('error.html', error="Dados do host incompletos"), 400

    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                              rightMargin=20, leftMargin=20,
                              topMargin=20, bottomMargin=20)

        styles = getSampleStyleSheet()
        elements = []
        
        # Estilo para títulos
        title_style = styles['Title']
        title_style.textColor = colors.HexColor('#0d6efd')
        title_style.fontName = 'Helvetica-Bold'
        
        # Estilo para cabeçalhos
        header_style = styles['Heading2']
        header_style.textColor = colors.HexColor('#212529')
        header_style.fontName = 'Helvetica-Bold'
        
        # Título principal
        elements.append(Paragraph(f"Relatório de Tráfego - {host_name}", title_style))
        elements.append(Spacer(1, 12))
        
        # Informações do host e interface
        host_info = [
            ["Grupo:", group_name],
            ["Host:", host_name],
            ["Interface:", interface],
            ["Período:", f"Últimos {period} minutos"],
            ["Gerado em:", datetime.now().strftime('%d/%m/%Y %H:%M:%S')]
        ]
        
        host_table = Table(host_info, colWidths=[1.5*inch, 4*inch])
        host_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#6c757d')),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.black),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(host_table)
        elements.append(Spacer(1, 24))
        
        # Gráfico principal
        elements.append(Paragraph("Tráfego da Interface", header_style))
        elements.append(Spacer(1, 12))
        
        img_data = base64.b64decode(main_graph)
        img = Image(BytesIO(img_data), width=5*inch, height=2.5*inch)
        elements.append(img)
        elements.append(Spacer(1, 12))
        
        # Adiciona esta nova seção para mostrar os valores simplificados
        elements.append(Paragraph("Resumo de Tráfego", header_style))
        elements.append(Spacer(1, 6))
        
        summary_data = [
            ["Métrica", "Valor"],
            ["Último Download", data['download'][-1]['formatted_value'] if data['download'] else "0 bps"],
            ["Último Upload", data['upload'][-1]['formatted_value'] if data['upload'] else "0 bps"],
            ["95º Percentil Download", percentile['download_formatted']],
            ["95º Percentil Upload", percentile['upload_formatted']]
        ]
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#D9E1F2")),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        elements.append(summary_table)

        # Estatísticas de tráfego
        elements.append(Paragraph("Estatísticas de Tráfego", header_style))
        elements.append(Spacer(1, 12))
        
        # Prepara os dados para a tabela
        max_download = max([d['value'] for d in data['download']]) if data['download'] else 0
        max_upload = max([u['value'] for u in data['upload']]) if data['upload'] else 0

        avg_download = sum([d['value'] for d in data['download']])/len(data['download']) if data['download'] else 0
        avg_upload = sum([u['value'] for u in data['upload']])/len(data['upload']) if data['upload'] else 0

        last_download = data['download'][-1]['formatted_value'] if data['download'] else "0 bps"
        last_upload = data['upload'][-1]['formatted_value'] if data['upload'] else "0 bps"

        tabela_dados = [
            ["Métrica", "Download", "Upload"],
            ["Máximo", format_speed(max_download), format_speed(max_upload)],
            ["Média", format_speed(avg_download), format_speed(avg_upload)],
            ["Último valor", last_download, last_upload],
            ["95º Percentil", percentile['download_formatted'], percentile['upload_formatted']]
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
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
        ]))
        
        elements.append(tabela)
        elements.append(Spacer(1, 24))
        
        # Constrói o PDF
        doc.build(elements)
        
        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=relatorio_trafego_{host_name}_{interface}_{period}min.pdf'
        return response
        
    except Exception as e:
        logger.error(f"Error in generate_pdf_response: {str(e)}\n{traceback.format_exc()}")
        return render_template('error.html', error=str(e)), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
