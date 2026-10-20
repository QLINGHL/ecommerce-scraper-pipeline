"""Spider for https://books.toscrape.com — a public scraping-practice site.

Crawl strategy:
  1. Walk every catalogue listing page (following the "next" pager).
  2. From each listing card, grab the cheap fields (title, price, rating,
     availability, product URL).
  3. Visit each book's detail page to pick up the UPC, which only lives
     in the product-information table there.

Raw values are passed through ``cb_kwargs`` so the pipelines receive the
untouched strings and do all cleaning in one place.
"""

import scrapy

from bookstore_scraper.items import BookItem


class BooksSpider(scrapy.Spider):
    name = "books"
    allowed_domains = ["books.toscrape.com"]
    start_urls = ["https://books.toscrape.com/catalogue/page-1.html"]

    def parse(self, response):
        """Parse one catalogue listing page."""
        for card in response.css("article.product_pod"):
            detail_url = card.css("h3 a::attr(href)").get()
            if not detail_url:
                continue

            rating_class = card.css("p.star-rating::attr(class)").get() or ""
            # class looks like "star-rating Three" -> keep just "Three"
            rating_word = rating_class.replace("star-rating", "").strip()

            yield response.follow(
                detail_url,
                callback=self.parse_book,
                cb_kwargs={
                    "title": card.css("h3 a::attr(title)").get(),
                    "price_raw": card.css(
                        "div.product_price p.price_color::text"
                    ).get(),
                    "rating_raw": rating_word,
                    "availability_raw": "".join(
                        card.css(
                            "div.product_price p.availability *::text"
                        ).getall()
                    ),
                },
            )

        # Follow the pager to the next catalogue page, if there is one.
        next_page = response.css("li.next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

    def parse_book(self, response, title, price_raw, rating_raw,
                   availability_raw):
        """Parse a book detail page; the UPC lives in the info table."""
        upc = response.xpath(
            "//table[contains(@class,'table-striped')]"
            "//th[normalize-space()='UPC']/following-sibling::td[1]/text()"
        ).get()

        # The listing card only says "In stock"; the detail page carries
        # the full text including the count, e.g. "In stock (22 available)".
        # Prefer the detail-page version when it has any text.
        detail_availability = "".join(
            response.css("p.availability *::text").getall()
        )
        if detail_availability.strip():
            availability_raw = detail_availability

        item = BookItem()
        item["title"] = title
        item["price_raw"] = price_raw
        item["rating_raw"] = rating_raw
        item["availability_raw"] = availability_raw
        item["product_url"] = response.url
        item["upc"] = upc
        yield item
