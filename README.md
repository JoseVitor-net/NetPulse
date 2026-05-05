# NetPulse

NetPulse é um aplicativo desktop profissional para monitoramento de rede e análise de latência.
Foi desenvolvido utilizando as melhores práticas de Engenharia de Software, padrão em camadas (MVC), e possui uma interface moderna (dark theme).

## Funcionalidades
- **Ping Avançado**: Modos Padrão, Customizado e Contínuo.
- **Métricas Precisas**: Latência, timeout, perda de pacotes, jitter, min, max, avg.
- **Dashboard Real-time**: Gráficos dinâmicos integrados com Plotly.
- **Relatórios**: Geração de relatórios HTML.
- **Persistência**: Histórico salvo localmente via SQLite.

## Estrutura do Projeto
- `app/ui`: Componentes de Interface Gráfica (PyQt6).
- `app/core`: Entidades de domínio e modelos de dados.
- `app/services`: Lógica de negócios (Ping concorrente, Relatórios).
- `app/infra`: Infraestrutura (Banco de dados, Logger).

## Como Rodar

1. Crie e ative um ambiente virtual:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/Mac:
   source venv/bin/activate
   ```

2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

3. Execute a aplicação:
   ```bash
   python main.py
   ```

## Testes
Para rodar os testes unitários:
```bash
pytest
```
