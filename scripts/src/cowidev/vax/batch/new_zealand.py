import re
from urllib.parse import urlparse

import pandas as pd
from bs4 import BeautifulSoup

from cowidev.vax.utils.utils import build_vaccine_timeline
from cowidev.utils.clean import clean_date_series, clean_date
from cowidev.utils.web.scraping import get_soup
from cowidev.utils.web.download import read_xlsx_from_url
from cowidev.utils import paths


class NewZealand:
    def __init__(self):
        # Consider: https://github.com/minhealthnz/nz-covid-data/tree/main/vaccine-data
        self.source_url = "https://www.health.govt.nz/our-work/diseases-and-conditions/covid-19-novel-coronavirus/covid-19-data-and-statistics/covid-19-vaccine-data"
        self.location = "New Zealand"
        self.columns_rename = {
            "First doses": "people_vaccinated",
            "Second doses": "people_fully_vaccinated",
            "Third primary doses": "third_dose",
            "Boosters": "total_boosters",
            "Date": "date",
        }
        self.columns_by_age_group_rename = {
            "# doses administered": "total_vaccinations",
            "Ten year age group": "age_group",
        }
        self.columns_cumsum = ["First doses", "Second doses", "Third primary doses", "Boosters"]
        self.columns_cumsum_by_age = ["Ten year age group"]

    def read(self) -> pd.DataFrame:
        soup = get_soup(self.source_url)

        # Get latest figures from HTML table
        latest = pd.read_html(str(soup.find("table")))[0]
        latest_date = re.search(r"Data in this section is as at 11:59pm ([\d]+ [A-Za-z]+ 202\d)", soup.text).group(1)
        self.latest = pd.DataFrame(
            {
                "total_vaccinations": latest.loc[latest["Unnamed: 0"] == "Total doses", "Cumulative total"].item(),
                "people_vaccinated": latest.loc[latest["Unnamed: 0"] == "First dose", "Cumulative total"].item(),
                "people_fully_vaccinated": latest.loc[
                    latest["Unnamed: 0"] == "Second dose", "Cumulative total"
                ].item(),
                "total_boosters": latest.loc[latest["Unnamed: 0"] == "Boosters", "Cumulative total"].item(),
                "third_dose": latest.loc[latest["Unnamed: 0"] == "Third primary", "Cumulative total"].item(),
                "date": [clean_date(latest_date, fmt="%d %B %Y", lang="en")],
            }
        )

        link = self._parse_file_link(soup)
        df = read_xlsx_from_url(link, sheet_name="Date")
        return df

    def _parse_file_link(self, soup: BeautifulSoup) -> str:
        href = soup.find(id="download").find_next("a")["href"]
        link = f"https://{urlparse(self.source_url).netloc}/{href}"
        return link

    def pipe_cumsum(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.columns_cumsum:
            df[self.columns_cumsum] = df[self.columns_cumsum].cumsum()
        return df

    def pipe_rename(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.columns_rename:
            return df.rename(columns=self.columns_rename)
        return df

    def pipe_merge_with_latest(self, df: pd.DataFrame) -> pd.DataFrame:
        df["date"] = df.date.astype(str)
        return pd.concat([df, self.latest]).drop_duplicates("date", keep="first").reset_index(drop=True)

    def pipe_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(
            total_vaccinations=df.people_vaccinated + df.people_fully_vaccinated + df.total_boosters + df.third_dose,
            total_boosters=df.total_boosters + df.third_dose,
        )

    def pipe_date(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(date=clean_date_series(df.date))

    def pipe_vaccine(self, df: pd.DataFrame) -> pd.DataFrame:
        return build_vaccine_timeline(df, {"Pfizer/BioNTech": "2021-01-01", "Oxford/AstraZeneca": "2021-11-26"})

    def pipe_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(
            location=self.location,
            source_url=self.source_url,
        )

    def pipe_columns_out(self, df: pd.DataFrame):
        return df[
            [
                "location",
                "date",
                "vaccine",
                "source_url",
                "people_vaccinated",
                "people_fully_vaccinated",
                "total_boosters",
                "total_vaccinations",
            ]
        ]

    def pipeline(self, df: pd.DataFrame) -> pd.DataFrame:
        return (
            df.pipe(self.pipe_cumsum)
            .pipe(self.pipe_rename)
            .pipe(self.pipe_merge_with_latest)
            .pipe(self.pipe_metrics)
            .pipe(self.pipe_date)
            .pipe(self.pipe_vaccine)
            .pipe(self.pipe_metadata)
            .pipe(self.pipe_columns_out)
        )

    def pipe_rename_by_age(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.columns_by_age_group_rename:
            return df.rename(columns=self.columns_by_age_group_rename)
        return df

    def pipe_aggregate_by_age(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.groupby("Ten year age group")["# doses administered"].sum().reset_index()
        return df

    def pipe_postprocess(self, df: pd.DataFrame, date_str: str) -> pd.DataFrame:
        df[["age_group_min", "age_group_max"]] = df.age_group.str.split(r" to |\+\/Unknown", expand=True)
        df["date"] = date_str
        df = df[["date", "age_group_min", "age_group_max", "total_vaccinations", "location"]]
        return df

    def pipeline_by_age(self, df: pd.DataFrame, date_str: str) -> pd.DataFrame:
        return (
            df.pipe(self.pipe_aggregate_by_age)
            .pipe(self.pipe_rename_by_age)
            .pipe(self.pipe_location)
            .pipe(self.pipe_postprocess, date_str)
        )

    def export(self):
        self.read().pipe(self.pipeline).to_csv(paths.out_vax(self.location), index=False)


def main():
    NewZealand().export()


if __name__ == "__main__":
    main()
