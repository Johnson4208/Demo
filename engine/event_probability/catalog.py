from __future__ import annotations

# Category -> factors. Each factor provides a focused online-research program.
# Outcomes are intentionally framed as directional regimes rather than pretending
# the engine can know an exact future event.
CATALOG = {
    "economy": {
        "label": "Economy",
        "factors": {
            "investing": {"label":"Investing & Risk Appetite","query":"Vietnam investing risk appetite stocks portfolio flows market outlook","event":"Will market risk appetite strengthen over the selected horizon?","outcomes":["Risk appetite strengthens","Risk appetite stays mixed","Risk appetite weakens"],"sources":"market"},
            "funds": {"label":"Funds & Capital Flows","query":"Vietnam funds ETF fund flows foreign institutional capital flows","event":"Will fund and institutional flows become more supportive?","outcomes":["Flows turn more supportive","Flows stay mixed","Flows weaken"],"sources":"market"},
            "interest_rates": {"label":"Interest Rates","query":"Vietnam interest rates monetary policy central bank rates outlook","event":"Will the rate environment become more accommodative?","outcomes":["More accommodative","Broadly stable","More restrictive"],"sources":"macro"},
            "inflation": {"label":"Inflation","query":"Vietnam inflation CPI price pressures outlook","event":"Will inflation pressure ease over the selected horizon?","outcomes":["Inflation pressure eases","Inflation stays contained/mixed","Inflation pressure rises"],"sources":"macro"},
            "jobs": {"label":"Employment","query":"Vietnam employment unemployment labor market jobs outlook","event":"Will labor-market conditions improve?","outcomes":["Labor conditions improve","Labor conditions stay stable","Labor conditions weaken"],"sources":"macro"},
            "gdp": {"label":"GDP & Growth","query":"Vietnam GDP economic growth outlook manufacturing exports domestic demand","event":"Will economic growth momentum improve?","outcomes":["Growth momentum improves","Growth remains stable/mixed","Growth momentum weakens"],"sources":"macro"},
            "fx": {"label":"FX & Currency","query":"Vietnam dong VND exchange rate USD VND currency outlook","event":"Will VND currency pressure ease?","outcomes":["Currency pressure eases","Currency remains range-bound","Currency pressure increases"],"sources":"market"},
        }
    },
    "markets": {
        "label":"Markets",
        "factors": {
            "equities": {"label":"Equities","query":"Vietnam stock market VN-Index equities outlook breadth liquidity valuation","event":"Will Vietnam equities maintain positive momentum?","outcomes":["Positive momentum strengthens","Market stays mixed/range-bound","Momentum weakens"],"sources":"market"},
            "bonds": {"label":"Bonds","query":"Vietnam government bond yields bond market duration outlook","event":"Will the bond backdrop become more supportive?","outcomes":["Bond backdrop improves","Bond backdrop stays mixed","Bond backdrop deteriorates"],"sources":"market"},
            "commodities": {"label":"Commodities","query":"oil gold copper commodity prices Asia Vietnam outlook","event":"Will commodity conditions become more favorable for regional risk assets?","outcomes":["Commodity backdrop improves","Commodity backdrop stays mixed","Commodity backdrop deteriorates"],"sources":"market"},
            "volatility": {"label":"Volatility","query":"Vietnam stock volatility VIX Asia volatility risk sentiment","event":"Will market volatility remain contained?","outcomes":["Volatility stays contained","Volatility remains mixed","Volatility spikes"],"sources":"market"},
        }
    },
    "banking": {
        "label":"Banking & Credit",
        "factors": {
            "credit": {"label":"Credit Growth","query":"Vietnam bank credit growth lending demand credit cycle banking outlook","event":"Will credit growth remain supportive?","outcomes":["Credit growth strengthens","Credit growth remains steady","Credit growth slows"],"sources":"banking"},
            "nim": {"label":"NIM & Margins","query":"Vietnam banks NIM net interest margin deposit loan rates banking earnings","event":"Will bank net interest margins improve?","outcomes":["Margins improve","Margins stay mixed","Margins compress"],"sources":"banking"},
            "npl": {"label":"Asset Quality / NPL","query":"Vietnam banks NPL bad debt asset quality provisioning","event":"Will banking asset-quality pressure ease?","outcomes":["Asset quality improves","Asset quality stays mixed","Asset-quality pressure rises"],"sources":"banking"},
        }
    },
    "business": {
        "label":"Business",
        "factors": {
            "earnings": {"label":"Earnings","query":"Vietnam corporate earnings revenue profit guidance outlook listed companies","event":"Will corporate earnings momentum improve?","outcomes":["Earnings momentum improves","Earnings stay mixed","Earnings momentum weakens"],"sources":"business"},
            "ma": {"label":"M&A","query":"Vietnam M&A mergers acquisitions transactions corporate deals outlook","event":"Will M&A activity strengthen?","outcomes":["M&A activity increases","M&A activity stays steady","M&A activity slows"],"sources":"business"},
            "capex": {"label":"Capex & Investment","query":"Vietnam corporate capex investment spending infrastructure manufacturing expansion","event":"Will business investment accelerate?","outcomes":["Investment accelerates","Investment stays steady","Investment slows"],"sources":"business"},
            "guidance": {"label":"Management Guidance","query":"Vietnam listed companies guidance outlook profit forecast revisions","event":"Will management guidance improve?","outcomes":["Guidance improves","Guidance stays mixed","Guidance weakens"],"sources":"business"},
        }
    },
    "technology": {
        "label":"Technology",
        "factors": {
            "ai": {"label":"AI & Compute","query":"AI data centers semiconductors hyperscalers Asia Vietnam technology outlook","event":"Will AI/compute investment momentum remain strong?","outcomes":["Momentum strengthens","Momentum stays strong/mixed","Momentum weakens"],"sources":"academic"},
            "semiconductors": {"label":"Semiconductors","query":"semiconductors chip demand Asia supply chain technology outlook","event":"Will semiconductor conditions improve?","outcomes":["Conditions improve","Conditions stay mixed","Conditions deteriorate"],"sources":"academic"},
            "cloud": {"label":"Cloud & Software","query":"cloud software enterprise IT spending Asia outlook","event":"Will enterprise cloud/software demand improve?","outcomes":["Demand improves","Demand stays stable","Demand weakens"],"sources":"academic"},
            "cybersecurity": {"label":"Cybersecurity","query":"cybersecurity threat enterprise security spending Asia outlook","event":"Will cybersecurity demand/risk intensity increase?","outcomes":["Demand/risk intensity rises","Conditions stay mixed","Demand/risk intensity eases"],"sources":"academic"},
        }
    },
    "health": {
        "label":"Health",
        "factors": {
            "pharma": {"label":"Pharma","query":"pharmaceutical drug approvals pipeline Asia health market outlook","event":"Will pharma sector conditions improve?","outcomes":["Conditions improve","Conditions stay mixed","Conditions weaken"],"sources":"academic"},
            "biotech": {"label":"Biotech","query":"biotech clinical trials drug development funding outlook","event":"Will biotech funding and development momentum improve?","outcomes":["Momentum improves","Momentum stays mixed","Momentum weakens"],"sources":"academic"},
            "public_health": {"label":"Public Health","query":"public health disease surveillance Asia health risk outlook","event":"Will public-health risk pressure rise?","outcomes":["Risk pressure rises","Risk remains mixed","Risk pressure eases"],"sources":"academic"},
        }
    },
    "geopolitics": {
        "label":"Geopolitics",
        "factors": {
            "trade": {"label":"Trade & Tariffs","query":"Vietnam trade tariffs exports supply chains Asia trade policy outlook","event":"Will trade friction intensify?","outcomes":["Trade friction intensifies","Trade conditions stay mixed","Trade friction eases"],"sources":"business"},
            "sanctions": {"label":"Sanctions","query":"Asia sanctions export controls geopolitics trade restrictions outlook","event":"Will sanctions/export-control pressure increase?","outcomes":["Pressure increases","Pressure stays mixed","Pressure eases"],"sources":"business"},
            "conflict": {"label":"Conflict Risk","query":"Asia geopolitical conflict security risk markets outlook","event":"Will geopolitical conflict risk increase?","outcomes":["Risk increases","Risk stays elevated/mixed","Risk eases"],"sources":"business"},
        }
    },
    "energy": {
        "label":"Energy",
        "factors": {
            "oil": {"label":"Oil","query":"oil prices OPEC Asia energy outlook","event":"Will oil prices/risk remain elevated?","outcomes":["Prices/risk increase","Prices stay range-bound","Prices/risk ease"],"sources":"market"},
            "gas": {"label":"Gas","query":"natural gas LNG Asia gas prices outlook","event":"Will gas market pressure increase?","outcomes":["Pressure increases","Market stays mixed","Pressure eases"],"sources":"market"},
            "renewables": {"label":"Renewables","query":"renewable energy investment solar wind Asia Vietnam outlook","event":"Will renewable-energy investment momentum strengthen?","outcomes":["Momentum strengthens","Momentum stays mixed","Momentum weakens"],"sources":"business"},
        }
    },
    "real_estate": {
        "label":"Real Estate",
        "factors": {
            "housing": {"label":"Housing","query":"Vietnam housing property residential real estate demand prices outlook","event":"Will residential real-estate conditions improve?","outcomes":["Conditions improve","Conditions stay mixed","Conditions weaken"],"sources":"business"},
            "commercial": {"label":"Commercial Property","query":"Vietnam commercial real estate office retail property outlook","event":"Will commercial property conditions improve?","outcomes":["Conditions improve","Conditions stay mixed","Conditions weaken"],"sources":"business"},
            "construction": {"label":"Construction","query":"Vietnam construction infrastructure public investment building outlook","event":"Will construction activity accelerate?","outcomes":["Activity accelerates","Activity stays steady","Activity slows"],"sources":"business"},
        }
    },
    "consumer": {
        "label":"Consumer",
        "factors": {
            "retail": {"label":"Retail","query":"Vietnam retail sales consumer spending outlook","event":"Will consumer spending strengthen?","outcomes":["Spending strengthens","Spending remains stable","Spending weakens"],"sources":"business"},
            "travel": {"label":"Travel & Tourism","query":"Vietnam tourism travel arrivals spending outlook Asia","event":"Will tourism demand strengthen?","outcomes":["Demand strengthens","Demand stays mixed","Demand weakens"],"sources":"business"},
            "autos": {"label":"Autos","query":"Vietnam automobile sales EV auto demand outlook","event":"Will auto demand improve?","outcomes":["Demand improves","Demand stays mixed","Demand weakens"],"sources":"business"},
        }
    },
    "science": {
        "label":"Science",
        "factors": {
            "climate_science": {"label":"Climate Science","query":"climate science extreme weather research outlook Asia","event":"Will climate-related risk intensity increase?","outcomes":["Risk intensity increases","Risk remains mixed","Risk intensity eases"],"sources":"academic"},
            "space": {"label":"Space","query":"space launch satellite research investment outlook","event":"Will space-sector activity accelerate?","outcomes":["Activity accelerates","Activity stays steady","Activity slows"],"sources":"academic"},
        }
    },
    "politics": {
        "label":"Politics & Policy",
        "factors": {
            "elections": {"label":"Elections","query":"Vietnam elections policy political outlook Asia","event":"Will political-policy uncertainty increase?","outcomes":["Uncertainty increases","Uncertainty stays mixed","Uncertainty eases"],"sources":"business"},
            "policy": {"label":"Policy","query":"Vietnam economic policy regulation government policy changes outlook","event":"Will policy conditions become more supportive for markets/business?","outcomes":["More supportive","Broadly stable/mixed","Less supportive"],"sources":"business"},
        }
    },
}


def public_catalog():
    return {
        ckey: {
            "label": cat["label"],
            "factors": {fkey: {"label": f["label"]} for fkey, f in cat["factors"].items()}
        }
        for ckey, cat in CATALOG.items()
    }
