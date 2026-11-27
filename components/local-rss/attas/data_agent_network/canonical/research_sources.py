"""Source-owned Taiwan research and analytic adapters with explicit coverage."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import copy
import re
import time

from prompits.core.resource_registry import reference
from prompits.core.pulse_models import validate_payload
from .research_models import PROFILES, ANALYTIC_SCHEMAS
from .finance import clean, number as native_number

def number(value):
    if isinstance(value,bool): return None
    return native_number(value.replace(',','').strip() if isinstance(value,str) else value)


def percent(value):
    """'20.1000%' → 20.1 (percentage points)."""
    return number(value.strip().rstrip('%') if isinstance(value,str) else value)


def thousands(value):
    """TWSE and TPEx state revenue and salaries in thousand TWD; rows carry TWD."""
    value = number(value)
    return round(value*1000, 3) if value is not None else None


def whole(value):
    value = number(value)
    return int(value) if value is not None and float(value).is_integer() else None


# TWSE and TPEx publish each dataset as one whole-market table. A model may read several of them: the first table is
# the one it can't do without, and the others fill more fields when the source has them installed (2026-11-25: company
# details, ESG, monthly revenue, announcements, EPS and margin balances, all from keyless open data).
TWSE_ESG = tuple('/opendata/t187ap46_L_'+str(n) for n in range(1,7))
TPEX_ESG = tuple('/t187ap46_O_'+str(n) for n in range(1,7))
OPERATIONS = {
 'twse': {'market.rankings.v1':'/exchangeReport/STOCK_DAY_ALL', 'market.quotes.v1':'/exchangeReport/STOCK_DAY_ALL',
          'company.profile.v1':('/exchangeReport/BWIBBU_ALL','/opendata/t187ap03_L','/opendata/t187ap05_L','/exchangeReport/STOCK_DAY_ALL'),
          'market.indices.v1':'/exchangeReport/MI_INDEX',
          'company.events.v1':'/exchangeReport/TWT48U_ALL','company.distributions.v1':'/exchangeReport/TWT48U_ALL',
          'company.esg.v1':TWSE_ESG, 'company.revenue-monthly.v1':'/opendata/t187ap05_L',
          'company.announcements.v1':'/opendata/t187ap04_L', 'company.earnings.v1':'/opendata/t187ap14_L',
          'company.margin.v1':'/exchangeReport/MI_MARGN'},
 'tpex': {'market.rankings.v1':'/tpex_mainboard_daily_close_quotes','market.quotes.v1':'/tpex_mainboard_daily_close_quotes',
          'company.profile.v1':('/tpex_mainboard_peratio_analysis','/mopsfin_t187ap03_O','/mopsfin_t187ap05_O','/tpex_mainboard_daily_close_quotes'),
          'market.indices.v1':'/tpex_index',
          'company.events.v1':'/tpex_exright_prepost','company.distributions.v1':'/tpex_exright_prepost',
          'company.esg.v1':TPEX_ESG, 'company.revenue-monthly.v1':'/mopsfin_t187ap05_O',
          'company.announcements.v1':'/mopsfin_t187ap04_O', 'company.earnings.v1':'/mopsfin_t187ap14_O',
          'company.margin.v1':'/tpex_mainboard_margin_balance', 'company.institutional.v1':'/tpex_3insti_daily_trading'},
 'finmind': {'company.institutional.v1':'TaiwanStockInstitutionalInvestorsBuySell',
             'company.margin.v1':'TaiwanStockMarginPurchaseShortSale',
             'fund.holdings.v1':'TaiwanStockActiveETFHolding',
             'company.distributions.v1':'TaiwanStockDividend', 'company.events.v1':'TaiwanStockDividend',
             'company.statement-items.v1':'TaiwanStockFinancialStatements'},
 'yfinance': {'fund.holdings.v1':'Ticker.funds_data',
              **{schema:'Ticker.history' for schema in ANALYTIC_SCHEMAS}},
}


# The fields each table of a several-table model gives, in the order of its operations.
PARTS = {
    'company.profile.v1': (('ticker','nameZh','priceEarnings','priceBook','dividendYieldPercent','currency'),
                           ('name','nameEn','country','website'), ('industry',), ('marketCap',)),
    'company.esg.v1': (('ticker','reportYear','scope1Emissions','scope2Emissions','scope3Emissions','emissionsIntensity','emissionsIntensityUnit'),
                       ('renewableEnergyPercent',), ('waterWithdrawal',), ('hazardousWaste','totalWaste'),
                       ('averageEmployeeSalary','femaleManagersPercent','currency'),
                       ('boardSeats','independentDirectors','femaleDirectors','femaleDirectorsPercent','boardAttendancePercent')),
}
# Models answered row by row from TWSE and TPEx's whole-market open-data tables (open_rows).
OPEN_SCHEMAS = ('company.profile.v1','company.esg.v1','company.revenue-monthly.v1','company.announcements.v1',
                'company.earnings.v1','company.margin.v1','company.institutional.v1')
# TPEx's daily institutional trading, per investor in shares (its foreign columns with and without foreign dealers, and
# its dealer total). Investor names follow FinMind's, which answers the same model.
FOREIGN = 'Foreign Investors include Mainland Area Investors (Foreign Dealers excluded)'
TPEX_INVESTORS = (('Foreign_Investor', FOREIGN+'-Total Buy', FOREIGN+'-Total Sell'),
                  ('Foreign_Dealer_Self', 'Foreign Dealers-Total Buy', 'Foreign Dealers-TotalSell'),
                  ('Investment_Trust', 'SecuritiesInvestmentTrustCompanies-TotalBuy', 'SecuritiesInvestmentTrustCompanies-TotalSell'),
                  ('Dealer', 'Dealers-TotalBuy', 'Dealers-TotalSell'))
EXCHANGE_EARNINGS_FIELDS = ['ticker','period','reportedEps','reportedRevenue','epsBasis','currency']
# Each table is one whole-market download, the same for every listing; a source reads it once per this many seconds.
OPEN_TABLE_SECONDS = 600


def operations(source, schema):
    """The operations a model reads, the one it can't do without first."""
    operation = OPERATIONS[source][schema]
    return operation if isinstance(operation, tuple) else (operation,)


def fields_for(source, schema):
    if source in ('twse','tpex') and schema in PARTS: return [f for part in PARTS[schema] for f in part]
    if schema == 'company.profile.v1': return ['ticker','nameZh','priceEarnings','priceBook','dividendYieldPercent']
    if schema == 'market.quotes.v1': return ['ticker','last','change','changePercent','volume','volumeUnit','volumeScope','currency','observedAt','priceKind']
    if schema == 'company.earnings.v1': return list(EXCHANGE_EARNINGS_FIELDS)
    fields = list(PROFILES[schema])
    if source in ('twse','tpex') and schema in ('company.events.v1','company.distributions.v1'):
        fields.remove('paymentDate')
    # TWSE's margin table has no date column.
    if source == 'twse' and schema == 'company.margin.v1':
        fields.remove('timestamp')
    if source == 'yfinance' and schema == 'fund.holdings.v1':
        fields = ['ticker','holdingId','holdingName','weightPercent']
    return fields


def operation_fields(source, schema, operation):
    """The fields one of a model's operations gives."""
    found = operations(source, schema)
    if len(found) == 1: return fields_for(source, schema)
    return list(PARTS[schema][found.index(operation)])


def owns(source, schema): return schema in OPERATIONS.get(source,{})


def date_value(value):
    if not value: return None
    value = str(value).strip()
    if re.fullmatch(r'\d{7}', value): return date(int(value[:3])+1911,int(value[3:5]),int(value[5:])).isoformat()
    if re.fullmatch(r'\d{8}', value): return date(int(value[:4]),int(value[4:6]),int(value[6:])).isoformat()
    if re.fullmatch(r'\d{2,3}/\d{1,2}/\d{1,2}', value):
        y,m,d = map(int,value.split('/')); return date(y+1911,m,d).isoformat()
    return date.fromisoformat(value.replace('/','-')[:10]).isoformat()


def roc_year(value):
    """'114' (ROC year) → 2025."""
    value = whole(value)
    return value+1911 if value is not None and value < 1911 else value


def roc_month(value):
    """'11510' (ROC year and month) → '2026-10'."""
    value = str(value or '').strip()
    if not re.fullmatch(r'\d{4,5}', value): return None
    return '%04d-%02d' % (int(value[:-2])+1911, int(value[-2:]))


def taipei_time(day, clock):
    """An announcement's date (ROC '1151124') and time ('70004' or '143005') in Taipei time."""
    when = date_value(day)
    clock = str(clock or '').strip()
    if not when or not re.fullmatch(r'\d{5,6}', clock): return when
    clock = clock.zfill(6)
    return f'{when}T{clock[:2]}:{clock[2:4]}:{clock[4:]}+08:00'


def text(value, join_lines=False):
    """Published text with Windows line ends; a subject's hard wraps join into one line."""
    if not isinstance(value, str): return None
    lines = [line.strip() for line in value.replace('\r\n','\n').replace('\r','\n').split('\n')]
    value = ('' if join_lines else '\n').join(line for line in lines if line)
    return value if value and value not in ('-','－') else None


def listing_code(row):
    return str(row.get('Code') or row.get('SecuritiesCompanyCode') or row.get('公司代號') or row.get('股票代號') or '').strip()


def website(value):
    value = text(value)
    if not value: return None
    return value if re.match(r'https?://', value) else 'https://'+value.lstrip('/')


def stripped(row):
    """Some open-data columns end in a space ('主旨 ')."""
    return {str(k).strip():v for k,v in row.items()} if isinstance(row, dict) else row


def keyed(row, prefix):
    """The value of the one column whose name starts with prefix, and that column's name."""
    for key, value in row.items():
        if key.startswith(prefix): return value, key
    return None, None


def open_rows(source, schema, tables, ticker, symbol=None):
    """Rows for one listing from an exchange's whole-market tables, in the order of operations(source, schema); a table
    the source doesn't have is None."""
    code = symbol if symbol is not None else ticker.rsplit('.',1)[0]
    matches = [[stripped(r) for r in rows if isinstance(r, dict) and listing_code(stripped(r)) == code] if rows is not None else []
               for rows in tables]
    first = [found[0] if found else None for found in matches]
    if schema == 'company.institutional.v1':
        rows = []
        for r in matches[0]:
            for investor, bought, sold in TPEX_INVESTORS:
                buy, sell = number(r.get(bought)), number(r.get(sold))
                if buy is None and sell is None: continue
                rows.append({'ticker':ticker,'timestamp':date_value(r.get('Date')),'investor':investor,'buyVolume':buy,'sellVolume':sell,
                             'netVolume':buy-sell if buy is not None and sell is not None else None,'volumeUnit':'shares'})
        return rows
    if schema == 'company.announcements.v1':
        return [{'ticker':ticker,'publishedAt':taipei_time(r.get('發言日期'),r.get('發言時間')),'eventAt':date_value(r.get('事實發生日')),
                 'headline':text(r.get('主旨'),True),'summary':text(r.get('說明')),'clause':text(r.get('符合條款'))} for r in matches[0]]
    if not first[0]: return []
    head = first[0]
    if schema == 'company.profile.v1':
        basic, monthly, quote = (first+[None]*4)[1:4]
        row = {'ticker':ticker,'nameZh':head.get('Name',head.get('CompanyName')),'currency':'TWD',
               'priceEarnings':number(head.get('PEratio',head.get('PriceEarningRatio'))),'priceBook':number(head.get('PBratio',head.get('PriceBookRatio'))),
               'dividendYieldPercent':number(head.get('DividendYield',head.get('YieldRatio')))}
        if basic:
            registered = text(basic.get('外國企業註冊地國',basic.get('Registration')))
            # A listing registered abroad names its country ("KY 開曼群島"); the others are Taiwan companies.
            row.update(name=text(basic.get('公司名稱',basic.get('CompanyName'))),nameEn=text(basic.get('英文簡稱',basic.get('Symbol'))),
                       country=registered or 'Taiwan',website=website(basic.get('網址',basic.get('WebAddress'))))
        if monthly: row['industry'] = text(monthly.get('產業別'))
        shares = number(basic.get('已發行普通股數或TDR原股發行股數',basic.get('IssueShares'))) if basic else None
        close = number(quote.get('ClosingPrice',quote.get('Close'))) if quote else None
        if shares and close: row['marketCap'] = round(shares*close, 2)
        return [row]
    if schema == 'company.esg.v1':
        ghg, energy, water, waste, people, board = (first+[None]*6)[:6]
        year = next((roc_year(r.get('報告年度')) for r in first if r and r.get('報告年度')), None)
        row = {'ticker':ticker,'reportYear':year,
               'scope1Emissions':number(ghg.get('範疇一排放量(噸CO2e)')),'scope2Emissions':number(ghg.get('範疇二排放量(噸CO2e)')),
               'scope3Emissions':number(ghg.get('範疇三排放量(噸CO2e)'))}
        intensity, column = keyed(ghg, '溫室氣體排放密集度')
        unit = re.search(r'\((.+)\)$', column or '')
        row.update(emissionsIntensity=number(intensity),emissionsIntensityUnit=unit.group(1) if unit and number(intensity) is not None else None)
        if energy: row['renewableEnergyPercent'] = percent(energy.get('使用率(再生能源/總能源)'))
        if water: row['waterWithdrawal'] = number(water.get('用水量(公噸)'))
        if waste: row.update(hazardousWaste=number(waste.get('有害廢棄物量-數據(公噸)')),totalWaste=number(waste.get('總重量(有害+非有害)-數據(公噸)')))
        if people:
            salary = thousands(people.get('員工薪資平均數(仟元/人)'))
            row.update(averageEmployeeSalary=salary,currency='TWD' if salary is not None else None,femaleManagersPercent=percent(people.get('管理職女性主管佔比')))
        if board:
            row.update(boardSeats=whole(board.get('董事席次(含獨立董事)(席)')),independentDirectors=whole(board.get('獨立董事席次(席)')),
                       femaleDirectors=whole(board.get('女性董事席次及比率-席')),femaleDirectorsPercent=percent(board.get('女性董事席次及比率-比率')),
                       boardAttendancePercent=percent(board.get('董事出席董事會出席率')))
        return [row]
    if schema == 'company.revenue-monthly.v1':
        return [{'ticker':ticker,'period':roc_month(head.get('資料年月')),'revenue':thousands(head.get('營業收入-當月營收')),
                 'revenueLastYear':thousands(head.get('營業收入-去年當月營收')),'revenueMomPercent':number(head.get('營業收入-上月比較增減(%)')),
                 'revenueYoyPercent':number(head.get('營業收入-去年同月增減(%)')),'revenueYtd':thousands(head.get('累計營業收入-當月累計營收')),
                 'revenueYtdYoyPercent':number(head.get('累計營業收入-前期比較增減(%)')),'remark':text(head.get('備註')),'currency':'TWD'}]
    if schema == 'company.earnings.v1':
        # Taiwan issuers report each quarter cumulatively: the third quarter's EPS covers January to September.
        year, quarter = roc_year(head.get('年度',head.get('Year'))), whole(head.get('季別'))
        period = (f'{year} Q1' if quarter == 1 else f'{year} Q1–Q{quarter}') if year and quarter else None
        return [{'ticker':ticker,'period':period,'reportedEps':number(head.get('基本每股盈餘(元)',head.get('基本每股盈餘'))),
                 'reportedRevenue':thousands(head.get('營業收入')),'epsBasis':'basic, year to date','currency':'TWD'}]
    if schema == 'company.margin.v1':
        return [{'ticker':ticker,'timestamp':date_value(head.get('Date')) if head.get('Date') else None,
                 'marginBalance':number(head.get('融資今日餘額',head.get('MarginPurchaseBalance'))),
                 'shortBalance':number(head.get('融券今日餘額',head.get('ShortSaleBalance'))),'volumeUnit':'lots'}]
    raise ValueError('Unsupported open-data model: '+schema)


def convert(source, schema, payload, ticker, args, source_symbol=None):
    records = payload.get('top_holdings',payload.get('data',payload.get('items',payload))) if isinstance(payload,dict) else payload
    if not isinstance(records,list):
        if source == 'yfinance' and isinstance(records,dict): records = [dict(row,holdingId=key) for key,row in records.items() if isinstance(row,dict)]
        else: raise ValueError('The research endpoint did not return observation records.')
    result=[]
    for r in records:
        if not isinstance(r,dict): raise ValueError('Research rows must be objects.')
        if source in ('twse','tpex'):
            code = r.get('Code',r.get('SecuritiesCompanyCode'))
            listing = str(code)+('.TW' if source=='twse' else '.TWO') if code else None
            if schema != 'market.indices.v1' and not listing: continue
            if schema != 'market.rankings.v1' and schema != 'market.indices.v1':
                if (str(code)!=source_symbol if source_symbol is not None else listing!=ticker):continue
                listing=ticker
            when = date_value(r.get('Date',r.get('日期')))
            row={'ticker':listing,'nameZh':r.get('Name',r.get('CompanyName')), 'currency':'TWD','observedAt':when}
            if schema in ('market.rankings.v1','market.quotes.v1'):
                last,delta=number(r.get('ClosingPrice',r.get('Close'))),number(r.get('Change'))
                row.update(last=last,change=delta,changePercent=100*delta/(last-delta) if last is not None and delta is not None and last!=delta else None,
                           volume=number(r.get('TradeVolume',r.get('TradingShares'))),volumeUnit='shares',volumeScope='session-cumulative',
                           turnover=number(r.get('TradeValue',r.get('TransactionAmount'))),priceKind='close')
            elif schema=='company.profile.v1':
                row.update(priceEarnings=number(r.get('PEratio',r.get('PriceEarningRatio'))),priceBook=number(r.get('PBratio',r.get('PriceBookRatio'))),dividendYieldPercent=number(r.get('DividendYield',r.get('YieldRatio'))))
            elif schema=='market.indices.v1':
                if source=='twse':
                    # TAIEX alone, unless the request asks for the whole table (sector and theme indices too).
                    if args.get('universe') not in (None,'all'): raise ValueError('Unsupported index universe.')
                    if r.get('指數') != '發行量加權股價指數' and args.get('universe') != 'all': continue
                    row.update(ticker='^TWII' if r.get('指數')=='發行量加權股價指數' else 'TWSE:'+str(r.get('指數')),
                               name=r.get('指數'),last=number(r.get('收盤指數')),change=number(r.get('漲跌點數')),changePercent=number(r.get('漲跌百分比')))
                    if str(r.get('漲跌','')).strip()=='-' and row['change'] is not None: row['change']=-abs(row['change'])
                else:
                    last,delta=number(r.get('Close')),number(r.get('Change'))
                    row.update(ticker='^TWOII',name='櫃買指數',last=last,change=delta,
                               changePercent=100*delta/(last-delta) if last is not None and delta is not None and last!=delta else None)
            else:
                row.update(eventAt=date_value(r.get('Date',r.get('ExRrightsExDividendDate'))),eventType='ex-dividend',
                           headline=r.get('Exdividend',r.get('ExRrightsExDividend')),cashDividend=number(r.get('CashDividend')))
        elif source=='finmind':
            if str(r.get('stock_id')) != (source_symbol if source_symbol is not None else ticker.split('.')[0]): continue
            row={'ticker':ticker,'timestamp':date_value(r.get('date'))}
            if schema=='company.institutional.v1':
                buy,sell=number(r.get('buy')),number(r.get('sell'))
                row.update(investor=r.get('name'),buyVolume=buy,sellVolume=sell,netVolume=buy-sell if buy is not None and sell is not None else None,volumeUnit='shares')
            elif schema=='company.margin.v1': row.update(marginBalance=number(r.get('MarginPurchaseTodayBalance')),shortBalance=number(r.get('ShortSaleTodayBalance')),volumeUnit='lots')
            elif schema=='fund.holdings.v1': row.update(asOf=row['timestamp'],holdingId=r.get('component_stock_id'),holdingName=r.get('component_stock_name'),weightPercent=number(r.get('weight')),shares=number(r.get('shares')),assetType=r.get('asset_type'),currency=r.get('currency'))
            elif schema=='company.statement-items.v1': row.update(period=row['timestamp'],metric=r.get('type'),name=r.get('origin_name'),value=number(r.get('value')),unit='provider-unspecified',periodType='source-reported')
            else: row.update(eventAt=date_value(r.get('CashExDividendTradingDate')),eventType='ex-dividend',headline='Cash distribution',cashDividend=number(r.get('CashEarningsDistribution')),paymentDate=date_value(r.get('CashDividendPaymentDate')),currency='TWD')
        else:
            weight=number(r.get('Holding Percent',r.get('holdingPercent')))
            row={'ticker':ticker,'holdingId':r.get('holdingId',r.get('Symbol',r.get('symbol',r.get('index')))),
                 'holdingName':r.get('Name',r.get('name')), 'weightPercent':weight*100 if weight is not None else None}
        result.append({k:v for k,v in row.items() if v is not None})
    # TPEx's index table holds the month's daily closes: the market's index is the latest of them.
    if schema=='market.indices.v1' and source=='tpex' and result:
        result=[max(result,key=lambda row:row.get('observedAt') or '')]
    if schema=='market.rankings.v1':
        sort=args.get('sort','turnover');direction=args.get('direction','descending')
        if sort not in ('turnover','volume','changePercent') or direction not in ('ascending','descending'): raise ValueError('Unsupported market ranking order.')
        limit=args.get('limit',30)
        if type(limit) is not int or not 1<=limit<=500:raise ValueError('Ranking limit must be between 1 and 500.')
        # The board lists warrants, ETFs and bonds too; 'stocks' keeps the four-digit common stocks, before the order
        # and the limit (2026-11-25: the top 500 TPEx losers were all warrants, TWSE's top gainers leveraged ETFs).
        listings=args.get('universe','all')
        if listings not in ('all','stocks'):raise ValueError('Unsupported market ranking universe.')
        result=[r for r in result if listings=='all' or re.fullmatch(r'[1-9]\d{3}\.TWO?',r['ticker'])]
        result=sorted((r for r in result if r.get(sort) is not None),key=lambda r:((-r[sort] if direction=='descending' else r[sort]),r['ticker']))[:limit]
        for i,row in enumerate(result): row.update(rank=i+1,method={'sort':sort,'direction':direction,'universe':source,'limit':limit,
                                                                   **({'listings':'stocks'} if listings=='stocks' else {})})
    return result


def execute(source, request, auth_context, schema):
    from .catalog import profile
    from .service import mapping_resource, implementation_digest
    model=profile(schema);mapping=mapping_resource(source.vendor_id,schema)
    if request.get('target_model')!=reference(model) or request.get('mapping_ref') not in (None,reference(mapping)):
        raise ValueError('Research model or mapping does not match the installed version.')
    query=request.get('model_request') or {}; fields=query.get('fields',fields_for(source.vendor_id,schema)); args=query.get('arguments',{})
    if not isinstance(args,dict) or not fields or any(f not in model['fields'] for f in fields):raise ValueError('Invalid research fields or arguments.')
    tickers=query.get('instruments',[])
    if not isinstance(tickers,list) or not 1<=len(tickers)<=12 or any(not isinstance(t,str) or not re.fullmatch(r'\^?[A-Z0-9]+(?:[.-][A-Z0-9]+)*(?:=[A-Z]+)?',t) for t in tickers):
        raise ValueError('Provide 1–12 Yahoo-style tickers.')
    unsupported = []
    symbols = {}
    if query.get('instrumentBindings') is not None:
        bindings=query['instrumentBindings']
        from ..symbology_config import configured
        declaration=configured(source.vendor_id,getattr(source,'_config_data',{}).get('source_profile',{}))
        accepted=declaration['input_types'] or declaration['output_types']
        if not isinstance(bindings,list) or len(bindings)!=len(tickers):raise ValueError('Provide one symbol binding per requested instrument.')
        for binding in bindings:
            if (not isinstance(binding,dict) or set(binding)!={'instrument','symbol','type'} or binding['instrument'] not in tickers
                    or binding['instrument'] in symbols or binding['type'] not in accepted
                    or not isinstance(binding['symbol'],str) or not re.fullmatch(r'[A-Za-z0-9.^=_/-]{1,80}',binding['symbol'])):
                raise ValueError('Invalid research source symbol binding.')
            if source.vendor_id in ('twse','tpex','finmind') and binding['type']!='TW_LOCAL':raise ValueError('Taiwan research requires local symbol bindings.')
            symbols[binding['instrument']]=binding['symbol']
        if len(set(symbols.values()))!=len(symbols):raise ValueError('Multiple listings map to the same source symbol.')
    if source.vendor_id in ('twse','tpex','finmind') and schema not in ('market.indices.v1','market.rankings.v1'):
        endings=('.TW',) if source.vendor_id=='twse' else ('.TWO',) if source.vendor_id=='tpex' else ('.TW','.TWO')
        unsupported = [t for t in tickers if not t.endswith(endings)]
        tickers = [t for t in tickers if t.endswith(endings)]
        if not tickers:raise ValueError('The selected source does not cover these listings.')
    if schema in ('market.rankings.v1','market.indices.v1'):
        expected = '^TWII' if source.vendor_id == 'twse' else '^TWOII'
        if tickers != [expected]: raise ValueError('This source does not cover the requested market universe.')
    names=operations(source.vendor_id,schema)
    def installed(name):
        actual='/data' if source.vendor_id=='finmind' else name
        found=next((e for e in source.spec_snapshot.endpoints if e.operation.removeprefix('yfinance.')==actual),None)
        return found if found and source.is_endpoint_executable(found) else None
    # The first operation is required; a later one only adds fields when the source has it installed.
    endpoints=[installed(name) for name in names]
    operation,endpoint=names[0],endpoints[0]
    if not endpoint:raise ValueError('Research operation is not installed: '+operation)
    rows=[];issues=[{'ticker':t,'status':'unsupported','reason':'Listing is outside this source market.'} for t in unsupported];costs=[]
    exchange=source.vendor_id in ('twse','tpex')
    tables=getattr(source,'_open_tables',None)
    if tables is None:
        tables={}
        try:setattr(source,'_open_tables',tables)
        except AttributeError:pass
    def fetch(found,params,failed_for):
        # An exchange table is the whole market, the same for every listing: read it once per OPEN_TABLE_SECONDS.
        kept=tables.get(found.endpoint_id) if exchange else None
        if kept and time.time()-kept[0]<OPEN_TABLE_SECONDS:return kept[1]
        fetched=source.execute_endpoint(found,params,auth_context);source._record_data_access_result(fetched);costs.append(dict(fetched.cost))
        if fetched.status!='completed':
            issues.extend({'ticker':t,'status':fetched.status,'reason':fetched.error or 'Provider did not return data.'} for t in failed_for);return None
        data=clean(fetched.data)
        if exchange:tables[found.endpoint_id]=(time.time(),data)
        return data
    if exchange and schema in OPEN_SCHEMAS:
        read=[]
        for name,found in zip(names,endpoints):
            data=fetch(found,{},tickers if name==operation else []) if found else None
            if isinstance(data,dict):data=data.get('data',data.get('items'))
            read.append(data if isinstance(data,list) else None)
        if read[0] is not None:
            for ticker in tickers:
                try:rows.extend({k:v for k,v in row.items() if v is not None} for row in open_rows(source.vendor_id,schema,read,ticker,symbols.get(ticker)))
                except (ValueError,TypeError,KeyError) as exc:issues.append({'ticker':ticker,'status':'invalid','reason':str(exc)})
    for ticker in [] if exchange and schema in OPEN_SCHEMAS else tickers[:1] if schema in ('market.rankings.v1','market.indices.v1') else tickers:
        params={}
        if source.vendor_id=='finmind':
            start=args.get('startDate',(date.today()-timedelta(days=365)).isoformat());end=args.get('endDate',date.today().isoformat())
            if not 0<=(date.fromisoformat(end)-date.fromisoformat(start)).days<=3653:raise ValueError('Research date range must be within ten years.')
            params={'dataset':operation,'data_id':symbols.get(ticker,ticker.split('.')[0]),'start_date':start,'end_date':end}
        elif source.vendor_id=='yfinance':
            params={'symbol':symbols.get(ticker,ticker)}
            if schema in ANALYTIC_SCHEMAS: params.update(period='2y',interval='1d',auto_adjust=False)
        data=fetch(endpoint,params,[ticker])
        if data is None:continue
        try:
            if schema in ANALYTIC_SCHEMAS:
                from .analytics import calculate
                from .finance import normalize
                bars=normalize(data,ticker,{'schema':'market.history.v1','fields':['ticker','timestamp','open','close']})
                rows.extend(calculate(bars,ticker,schema,args))
            else: rows.extend(convert(source.vendor_id,schema,data,ticker,args,symbols.get(ticker)))
        except (ValueError,TypeError,KeyError) as exc: issues.append({'ticker':ticker,'status':'invalid','reason':str(exc)})
    # Strict display projection: no provider fields or unrequested hidden data.
    rows=[{f:r[f] for f in fields if f in r} for r in rows]
    validate_payload(model,rows)
    received=time.time();missing=[f for f in fields if not rows or any(r.get(f) is None for r in rows)]
    # Which operation gave each field: a several-table model names the table each field comes from.
    by_field={f:(operation,endpoint) for f in fields}
    for name,found in zip(names,endpoints):
        for f in (operation_fields(source.vendor_id,schema,name) if len(names)>1 else []):
            if f in by_field and found:by_field[f]=(name,found)
    envelope={'schema':'canonical-result/1','modelRef':reference(model),'mappingRefs':[reference(mapping)],
        'payload':rows,'missingFields':missing,'issues':issues,'sourceId':source.vendor_id,'receivedAt':received,
        'implementationDigest':implementation_digest(),'verification':'declared','endpointIds':[e.endpoint_id for e in endpoints if e],
        'costs':costs,'lineage':[{f:{'sourceId':source.vendor_id,'endpointId':by_field[f][1].endpoint_id,'operation':by_field[f][0],
            'status':'available' if f in row else 'missing','modelFieldRef':model['fields'][f],'receivedAt':received} for f in fields} for row in rows]}
    failed = not rows and bool(issues)
    return {'status':'failed' if failed else 'completed','canonical_result':envelope,'canonical_data':{'items':rows},
            'data':{'items':rows},'warnings':[i['reason'] for i in issues], 'error':'No research observations available.' if failed else ''}
