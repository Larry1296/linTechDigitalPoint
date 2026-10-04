import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { LedgerPage } from './LedgerPage';
import { api } from '../../core/api/client';
vi.mock('../../core/api/client',()=>({api:vi.fn()}));
vi.mock('../../core/auth/AuthContext',()=>({useAuth:()=>({user:{branch:{id:1},branches:[{id:1,name:'Main'}]}})}));
beforeEach(()=>api.mockResolvedValue({currency:'KES',basis:'Posted journals only',profit_loss:{revenue:1000,cogs:400,gross_profit:600,expenses:200,net_profit:400},balance_sheet:{assets:400,liabilities:0,equity:0,retained_earnings:400,difference:0},cash_movement:{opening:0,net_movement:800,closing:800},trial_balance:[],debits:1600,credits:1600,journals:{count:1,results:[{id:1,posting_date:'2026-09-22',description:'Sale A',source_key:'sale:1',lines:[{account:'4000',name:'Sales',debit:0,credit:1000}]}]}}));
it('shows gross and net profit separately with source transactions and honest opening coverage',async()=>{
 render(<LedgerPage/>);
 expect(await screen.findByRole('heading',{name:'Profit and loss'})).toBeInTheDocument();
 expect(screen.getByText('Gross profit').nextSibling).toHaveTextContent('600.00');
 expect(screen.getByText('Net profit').nextSibling).toHaveTextContent('400.00');
 expect(screen.getByText(/do not claim a complete opening/)).toBeInTheDocument();
 expect(screen.getByText(/Sale A/)).toBeInTheDocument();
});
