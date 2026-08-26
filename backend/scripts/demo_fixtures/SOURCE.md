# Vendored demo data

## `northwind_orders.csv.gz`

The one dataset in the seed that is **real rather than generated**. Everything
else the seed produces is synthesised from a seeded RNG, which is fine for
exercising ingestion but makes a poor demo: the analysis engine's whole claim
is that it computes over a real file, and a file invented to be computed over
undercuts that.

**Source:** [jpwhite3/northwind-SQLite3](https://github.com/jpwhite3/northwind-SQLite3),
the enlarged edition of Microsoft's long-published Northwind sample database.

**Licence:** MIT. Redistribution and modification are permitted with the notice
retained; that is why this file exists rather than a Kaggle download, where the
licence is set per dataset and a fair number are non-commercial.

**Shape:** 110,064 order lines across the two complete calendar years 2021 and
2022. Partial years are excluded on purpose — the source runs from mid-2012 to
October 2023, and a year-over-year question that silently compares twelve
months against ten reports a category as "fastest growing" while it shrank.

**Columns:** `order_date`, `month`, `country`, `category`, `product`,
`sales_rep`, `quantity`, `unit_price`, `discount`, `revenue`, `freight`,
`days_to_ship`.

**Why gzipped:** 1.2 MB against 11 MB uncompressed. Seeding stays offline and
reproducible without the repository carrying eleven megabytes of CSV forever.
`generate_demo_data.py` expands it in memory before upload.

### Regenerating it

```bash
curl -sL -o northwind.db \
  https://raw.githubusercontent.com/jpwhite3/northwind-SQLite3/main/dist/northwind.db

sqlite3 -header -csv northwind.db "
select
  date(o.OrderDate)                                      as order_date,
  strftime('%Y-%m', o.OrderDate)                         as month,
  o.ShipCountry                                          as country,
  c.CategoryName                                         as category,
  p.ProductName                                          as product,
  e.FirstName || ' ' || e.LastName                       as sales_rep,
  d.Quantity                                             as quantity,
  round(d.UnitPrice, 2)                                  as unit_price,
  round(d.Discount, 2)                                   as discount,
  round(d.UnitPrice * d.Quantity * (1 - d.Discount), 2)  as revenue,
  round(o.Freight, 2)                                    as freight,
  cast(julianday(o.ShippedDate) - julianday(o.OrderDate) as int) as days_to_ship
from 'Order Details' d
join Orders o     on o.OrderID   = d.OrderID
join Products p   on p.ProductID = d.ProductID
join Categories c on c.CategoryID = p.CategoryID
left join Employees e on e.EmployeeID = o.EmployeeID
where o.OrderDate >= '2021-01-01' and o.OrderDate < '2023-01-01'
order by o.OrderDate;
" > northwind_orders.csv

gzip -9 -c northwind_orders.csv > northwind_orders.csv.gz
```

If you extend the range, keep it to whole years and keep the file under the
API's upload ceiling (`MAX_UPLOAD_MB`, 25 MB by default).
