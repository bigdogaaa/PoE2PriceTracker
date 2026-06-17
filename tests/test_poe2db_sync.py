from poe2_price_tracker.poe2db_sync import parse_economy_html


def test_parse_economy_html_keeps_currency_icon_url():
    html = """
    <table>
      <tr>
        <th>名称</th><th>24h Value</th><th>Last 7 days</th>
      </tr>
      <tr>
        <td><a href="/cn/Economy_mirror">卡兰德的魔镜</a><a>Wiki</a></td>
        <td>
          2600 <a href="/cn/Economy_divine"><img src="https://web.poecdn.com/divine.png"></a>
          1 <a href="/cn/Economy_mirror"><img src="https://web.poecdn.com/mirror.png"></a>
        </td>
        <td>+17%</td>
      </tr>
    </table>
    """

    result = parse_economy_html(html, "通货", "https://poe2db.tw/cn/Economy_Currency")

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.item_name == "卡兰德的魔镜"
    assert row.amount == 2600
    assert row.currency == "神圣石"
    assert row.currency_icon_url == "https://web.poecdn.com/divine.png"
    assert row.item_icon_url == "https://web.poecdn.com/mirror.png"
