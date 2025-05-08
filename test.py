from zabbix_api import ZabbixAPI

# Configurações
ZABBIX_URL = "http://192.168.4.23/zabbix/api_jsonrpc.php"
ZABBIX_TOKEN = "4fb8566a7f4cf77b5ae5c215dbe3a167149d406bbe9ada7c5b4af82ec1590504"
HOSTID = "10665"  # Substitua pelo hostid que deseja testar

def get_interfaces(zapi, hostid):
    """Busca específica para seu ambiente Zabbix"""
    try:
        # Busca os itens exatos que você mostrou no teste
        items = zapi.item.get({
            "hostids": hostid,
            "output": ["itemid", "name", "key_", "type"],
            "filter": {
                "key_": [
                    "net.if.in[ifHCInOctets.2]",
                    "net.if.out[ifHCOutOctets.2]"
                ],
                "status": "0"
            }
        })
        
        print("\nItens encontrados:")
        for item in items:
            print(f"- {item['name']} ({item['key_']})")
            
        # Extrai o número da interface (2 no seu caso)
        interfaces = set()
        for item in items:
            if 'ifHCInOctets.2' in item['key_'] or 'ifHCOutOctets.2' in item['key_']:
                interfaces.add('2')  # Número fixo conforme seus itens
        
        return sorted(list(interfaces))
    
    except Exception as e:
        print(f"Erro: {str(e)}")
        return []

if __name__ == '__main__':
    print("=== TESTE ESPECÍFICO PARA SEU AMBIENTE ===")
    zapi = ZabbixAPI(server=ZABBIX_URL)
    zapi.login(api_token=ZABBIX_TOKEN)
    
    interfaces = get_interfaces(zapi, HOSTID)
    print("\n=== RESULTADO ===")
    print(f"Interfaces encontradas: {interfaces}")
