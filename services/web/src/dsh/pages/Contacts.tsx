import type { Customer, Vendor } from "../rest";
import { useApi } from "../useApi";
import { Cell, Page, PageState, Row, Table } from "./ui";

function ContactTable({ rows, kind }: { rows: Array<Customer | Vendor>; kind: string }) {
  return (
    <Table
      head={
        <tr>
          <th className="px-3 py-1.5 text-left font-semibold">{kind}</th>
          <th className="px-3 py-1.5 text-left font-semibold">Email</th>
          <th className="hidden px-3 py-1.5 text-left font-semibold sm:table-cell">Phone</th>
        </tr>
      }
    >
      {rows.map((row) => (
        <Row key={row.id}>
          <Cell>{row.name}</Cell>
          <Cell className="text-neutral-500">{row.email ?? "—"}</Cell>
          <Cell className="hidden text-neutral-500 sm:table-cell">{row.phone ?? "—"}</Cell>
        </Row>
      ))}
    </Table>
  );
}

export function CustomersPage() {
  const { data, error, loading } = useApi<{ customers: Customer[]; count: number }>("/api/customers");
  return (
    <Page title="Customers" meta={data !== null ? `${data.count}` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? <ContactTable rows={data.customers} kind="Customer" /> : null}
      </PageState>
    </Page>
  );
}

export function VendorsPage() {
  const { data, error, loading } = useApi<{ vendors: Vendor[]; count: number }>("/api/vendors");
  return (
    <Page title="Vendors" meta={data !== null ? `${data.count}` : undefined}>
      <PageState loading={loading} error={error} empty={data !== null && data.count === 0}>
        {data !== null ? <ContactTable rows={data.vendors} kind="Vendor" /> : null}
      </PageState>
    </Page>
  );
}
