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

app = Flask(__name__)

# Configuração básica de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/api/hosts', methods=['GET'])
def api_get_hosts():
    try:
        zapi = get_zabbix()
        hosts = get_hosts(zapi)
        return jsonify(hosts)
    except Exception as e:
        logger.error(f"Error in api_get_hosts: {str(e)}")
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
        logger.error(f"Error in api_get_interfaces: {str(e)}")
        return jsonify({'error': str(e)}), 500

def format_speed(value, pos=None):
    """Formatador para converter valores de velocidade em unidades apropriadas"""
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
        
        # Obtém grupos (formato corrigido)
        groups = zapi.hostgroup.get(
            output=["groupid", "name"],
            sortfield="name",
            with_monitored_hosts=True,
            with_hosts=True
        )
        
        # Obtém hosts (formato corrigido)
        hosts = zapi.host.get(
            output=["hostid", "name"],
            filter={"status": "0"},
            monitored_hosts=True,
            selectGroups=["groupid", "name"],
            preservekeys=True
        )
        
        return render_template('index.html', 
                           hosts=list(hosts.values()),
                           groups=groups)
    
    except Exception as e:
        logger.error(f"Error in index: {str(e)}")
        return render_template('error.html', error=str(e))

@app.route('/report', methods=['POST'])
def generate_report():
    try:
        hostid = request.form['host']
        interface = request.form.get('interface')  # Novo parâmetro
        period = int(request.form.get('period', 15))

        zapi = get_zabbix()
        
        # Obtém itens de interface de forma mais robusta
        items = zapi.item.get({
            "hostids": hostid,
            "search": {"key_": f"net.if.*[{interface}]"},  # Filtra pela interface
            "filter": {"type": "4"},  # Itens normais (não dependentes)
            "output": ["itemid", "name", "key_", "value_type"],
            "selectInterfaces": ["interfaceid"]
        })

        if not items:
            raise ValueError("Nenhum item de interface encontrado para este host")

        # Obtém dados históricos
        time_till = int(time.time())
        time_from = time_till - (period * 60)
        
        data = {"download": [], "upload": []}
        
        for item in items:
            try:
                history = zapi.history.get({
                    "itemids": item['itemid'],
                    "time_from": time_from,
                    "time_till": time_till,
                    "output": "extend",
                    "sortfield": "clock",
                    "sortorder": "ASC",
                    "history": item['value_type'],
                    "limit": 1000
                })

                values = []
                for point in history:
                    timestamp = datetime.fromtimestamp(int(point['clock']))
                    value = (float(point['value']) * 8) / 1000  # Convert bytes to bits then to kbps
                    values.append({
                        "timestamp": timestamp,
                        "value": value,
                        "formatted_value": format_speed(value)
                    })

                if "net.if.in" in item['key_']:
                    data["download"] = values
                elif "net.if.out" in item['key_']:
                    data["upload"] = values

            except Exception as e:
                logger.warning(f"Error processing item {item['itemid']}: {str(e)}")
                continue

        # Verifica se há dados para mostrar
        if not data["download"] and not data["upload"]:
            raise ValueError("Nenhum dado histórico encontrado para o período selecionado")

        # Cálculo de percentis
        percentile_data = {
            "download": calculate_percentile(data["download"]) if data["download"] else 0,
            "upload": calculate_percentile(data["upload"]) if data["upload"] else 0
        }

        # Geração de gráficos (mesmo código que você tinha, apenas removido para brevidade)
        # ... [seu código existente para geração de gráficos] ...

        if request.form.get('generate_pdf'):
            return generate_pdf_response(
                period, 
                main_graph_base64, 
                data, 
                gauge_download_base64,
                gauge_upload_base64,
                gauge_percentile_base64,
                percentile_data
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
                     percentile=percentile_data)
    
    except Exception as e:
        logger.error(f"Error in generate_report: {str(e)}")
        return render_template('error.html', error=str(e))

def generate_pdf_response(period, main_graph, data, gauge_download, gauge_upload, gauge_percentile, percentile):
    try:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                              rightMargin=40, leftMargin=40,
                              topMargin=40, bottomMargin=40)

        styles = getSampleStyleSheet()
        elements = []
        
        # [restante do seu código para geração de PDF...]
        
    except Exception as e:
        logger.error(f"Error in generate_pdf_response: {str(e)}")
        return render_template('error.html', error=str(e))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
