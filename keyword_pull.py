"""
Pulls keyword ideas and search volumes from Google Ads Keyword Planner.
Results are saved to keywords.csv.
"""

import csv
from google.ads.googleads.client import GoogleAdsClient

CUSTOMER_ID = "8002284491"

SEED_KEYWORDS = [
    "benefits verification automation",
    "prior authorization automation",
    "payer call automation",
    "revenue cycle AI",
    "healthcare voice AI",
    "claim status automation",
    "RCM automation software",
    "eligibility verification software",
    "denial management automation",
    "AI voice agents healthcare",
]

def get_keyword_ideas(client, customer_id, keywords):
    keyword_plan_idea_service = client.get_service("KeywordPlanIdeaService")
    request = client.get_type("GenerateKeywordIdeasRequest")

    request.customer_id = customer_id
    request.language = "languageConstants/1000"  # English
    request.geo_target_constants.append("geoTargetConstants/2840")  # United States
    request.include_adult_keywords = False
    request.keyword_seed.keywords.extend(keywords)

    response = keyword_plan_idea_service.generate_keyword_ideas(request=request)
    return response

def main():
    client = GoogleAdsClient.load_from_storage("google-ads.yaml")
    print(f"Pulling keyword ideas for {len(SEED_KEYWORDS)} seed keywords...\n")

    response = get_keyword_ideas(client, CUSTOMER_ID, SEED_KEYWORDS)

    results = []
    for idea in response:
        keyword = idea.text
        avg_monthly_searches = idea.keyword_idea_metrics.avg_monthly_searches
        competition = idea.keyword_idea_metrics.competition.name
        low_cpc = idea.keyword_idea_metrics.low_top_of_page_bid_micros / 1_000_000
        high_cpc = idea.keyword_idea_metrics.high_top_of_page_bid_micros / 1_000_000

        results.append({
            "keyword": keyword,
            "avg_monthly_searches": avg_monthly_searches,
            "competition": competition,
            "low_cpc": round(low_cpc, 2),
            "high_cpc": round(high_cpc, 2),
        })

    # Sort by search volume descending
    results.sort(key=lambda x: x["avg_monthly_searches"], reverse=True)

    # Save to CSV
    output_file = "keywords.csv"
    with open(output_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["keyword", "avg_monthly_searches", "competition", "low_cpc", "high_cpc"])
        writer.writeheader()
        writer.writerows(results)

    print(f"Done. {len(results)} keywords saved to {output_file}\n")
    print("Top 20 by search volume:")
    print(f"{'Keyword':<50} {'Searches':>10} {'Competition':>12} {'CPC Range':>15}")
    print("-" * 90)
    for r in results[:20]:
        print(f"{r['keyword']:<50} {r['avg_monthly_searches']:>10,} {r['competition']:>12} ${r['low_cpc']:>6.2f}–${r['high_cpc']:.2f}")

if __name__ == "__main__":
    main()
