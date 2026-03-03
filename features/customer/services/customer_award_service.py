# src/features/customer/services/customer_award_service.py

import json
from datetime import datetime
from typing import Dict, Any, List
from ....common.db_pyodbc import get_db_connection
from ....common.logging_config import get_logger
from ....common.config import Config

logger = get_logger(__name__)

class CustomerAwardService:
    """
    Service for customer to view and confirm award proposals
    """
    
    def __init__(self):
        self.connection = None
        self.cursor = None
    
    def __enter__(self):
        self.connection = get_db_connection()
        self.cursor = self.connection.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
    
    def get_proposal_for_confirmation(self, proposal_id: int, access_token: str) -> Dict[str, Any]:
        """
        Get proposal details for customer confirmation (with token validation)
        """
        try:
            # Get proposal details
            self.cursor.execute("""
                SELECT 
                    p.proposal_id,
                    p.rfq_id,
                    p.proposal_data,
                    p.total_amount,
                    p.currency,
                    p.status,
                    p.expires_at,
                    p.sent_at,
                    p.viewed_at,
                    p.responded_at,
                    h.department,
                    h.required_date,
                    h.delivery_deadline,
                    h.created_at
                FROM [RFQ].[rfq_customer_proposals] p
                JOIN [RFQ].[rfq_headers] h ON p.rfq_id = h.rfq_id
                WHERE p.proposal_id = ?
            """, (proposal_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Proposal not found"}
            
            # Validate access token
            try:
                proposal_data = json.loads(row[2])
                stored_token = proposal_data.get('access_token')
                if stored_token != access_token:
                    return {"status": "error", "message": "Invalid access token"}
            except Exception as e:
                logger.error(f"Error parsing proposal data: {str(e)}")
                return {"status": "error", "message": "Invalid proposal data"}
            
            # Check if proposal is still pending
            if row[5] != 'PENDING':
                return {"status": "error", "message": f"This proposal has already been {row[5].lower()}"}
            
            # Check if expired
            if row[6] and datetime.now() > row[6]:
                return {"status": "error", "message": "This proposal has expired"}
            
            # Update viewed timestamp if not already viewed
            if not row[8]:
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_customer_proposals]
                    SET viewed_at = GETDATE()
                    WHERE proposal_id = ?
                """, (proposal_id,))
                self.connection.commit()
            
            # Get proposal items with supplier details
            self.cursor.execute("""
                SELECT 
                    pi.line_number,
                    pi.awarded_quantity,
                    pi.unit_price,
                    pi.total_price,
                    pi.currency,
                    s.supplier_id,
                    s.company_name,
                    s.contact_person,
                    s.email,
                    s.phone,
                    li.category,
                    li.brand,
                    li.model,
                    li.part_number,
                    li.description,
                    li.specifications
                FROM [RFQ].[rfq_proposal_items] pi
                JOIN [RFQ].[suppliers] s ON pi.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_line_items] li ON pi.line_number = li.line_number AND li.rfq_id = ?
                WHERE pi.proposal_id = ?
                ORDER BY pi.line_number
            """, (row[1], proposal_id))
            
            items = []
            total_by_supplier = {}
            
            for item_row in self.cursor.fetchall():
                supplier_name = item_row[6]
                if supplier_name not in total_by_supplier:
                    total_by_supplier[supplier_name] = 0
                
                item_total = float(item_row[3])
                total_by_supplier[supplier_name] += item_total
                
                # Parse specifications
                try:
                    specs = json.loads(item_row[15]) if item_row[15] else {}
                except:
                    specs = {}
                
                items.append({
                    "line_number": item_row[0],
                    "quantity": float(item_row[1]),
                    "unit_price": float(item_row[2]),
                    "total_price": item_total,
                    "currency": item_row[4] or "USD",
                    "supplier": {
                        "supplier_id": item_row[5],
                        "company_name": supplier_name,
                        "contact_person": item_row[7],
                        "email": item_row[8],
                        "phone": item_row[9]
                    },
                    "product_details": {
                        "category": item_row[10] or "",
                        "brand": item_row[11] or "",
                        "model": item_row[12] or "",
                        "part_number": item_row[13] or "",
                        "description": item_row[14] or "",
                        "specifications": specs
                    }
                })
            
            # Format response
            return {
                "status": "success",
                "proposal": {
                    "proposal_id": row[0],
                    "rfq_id": row[1],
                    "total_amount": float(row[3]),
                    "currency": row[4] or "USD",
                    "status": row[5],
                    "expires_at": row[6].isoformat() if row[6] else None,
                    "sent_at": row[7].isoformat() if row[7] else None,
                    "viewed_at": datetime.now().isoformat(),
                    "department": row[10],
                    "required_date": row[11].isoformat() if row[11] else None,
                    "delivery_deadline": row[12].isoformat() if row[12] else None,
                    "rfq_created_at": row[13].isoformat() if row[13] else None
                },
                "items": items,
                "summary_by_supplier": [
                    {
                        "supplier_name": name,
                        "total_amount": total,
                        "currency": row[4] or "USD"
                    }
                    for name, total in total_by_supplier.items()
                ],
                "notes": proposal_data.get('notes', '')
            }
            
        except Exception as e:
            logger.error(f"Error getting proposal for confirmation: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def confirm_proposal(self, proposal_id: int, access_token: str, 
                        confirmation_notes: str = None) -> Dict[str, Any]:
        """
        Customer confirms the proposal - this finalizes the awards
        """
        try:
            # Get proposal details with validation
            self.cursor.execute("""
                SELECT 
                    p.proposal_id,
                    p.rfq_id,
                    p.proposal_data,
                    p.total_amount,
                    p.currency,
                    p.status,
                    p.expires_at
                FROM [RFQ].[rfq_customer_proposals] p
                WHERE p.proposal_id = ?
            """, (proposal_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Proposal not found"}
            
            # Validate access token
            try:
                proposal_data = json.loads(row[2])
                stored_token = proposal_data.get('access_token')
                if stored_token != access_token:
                    return {"status": "error", "message": "Invalid access token"}
            except:
                return {"status": "error", "message": "Invalid proposal data"}
            
            # Check status
            if row[5] != 'PENDING':
                return {"status": "error", "message": f"Proposal is already {row[5].lower()}"}
            
            # Check if expired
            if row[6] and datetime.now() > row[6]:
                return {"status": "error", "message": "This proposal has expired"}
            
            rfq_id = row[1]
            currency = row[4] or 'USD'
            
            # Update proposal status
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_customer_proposals]
                SET status = 'APPROVED',
                    responded_at = GETDATE(),
                    response_notes = ?
                WHERE proposal_id = ?
            """, (confirmation_notes, proposal_id))
            
            # Get all proposal items
            self.cursor.execute("""
                SELECT 
                    line_number,
                    supplier_id,
                    awarded_quantity,
                    unit_price,
                    total_price,
                    supplier_mapping_id
                FROM [RFQ].[rfq_proposal_items]
                WHERE proposal_id = ?
            """, (proposal_id,))
            
            proposal_items = self.cursor.fetchall()
            
            # Track awarded suppliers for notifications
            awarded_suppliers = set()
            awarded_mappings = set()
            
            # Create final awards
            for item in proposal_items:
                line_num = item[0]
                supplier_id = item[1]
                quantity = float(item[2])
                unit_price = float(item[3])
                total_price = float(item[4])
                mapping_id = item[5]
                
                awarded_suppliers.add(supplier_id)
                if mapping_id:
                    awarded_mappings.add(mapping_id)
                
                # Insert into final awards
                self.cursor.execute("""
                    INSERT INTO [RFQ].[rfq_final_awards]
                    (proposal_id, line_number, supplier_id, awarded_quantity, 
                     unit_price, total_price, currency, award_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, GETDATE())
                """, (
                    proposal_id,
                    line_num,
                    supplier_id,
                    quantity,
                    unit_price,
                    total_price,
                    currency
                ))
                
                # Update line items - move from pending to awarded
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_line_items]
                    SET awarded_quantity = ISNULL(awarded_quantity, 0) + ?,
                        pending_award_quantity = ISNULL(pending_award_quantity, 0) - ?,
                        award_status = 'AWARDED'
                    WHERE rfq_id = ? AND line_number = ?
                """, (quantity, quantity, rfq_id, line_num))
            
            # Update supplier statuses
            if awarded_mappings:
                # Update awarded suppliers
                mapping_placeholders = ','.join(['?'] * len(awarded_mappings))
                self.cursor.execute(f"""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET status = 'AWARDED'
                    WHERE mapping_id IN ({mapping_placeholders})
                """, *list(awarded_mappings))
                
                # Update other suppliers to LOST
                self.cursor.execute(f"""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET status = 'LOST'
                    WHERE rfq_id = ? AND mapping_id NOT IN ({mapping_placeholders})
                    AND quotation_received = 1
                """, (rfq_id, *list(awarded_mappings)))
            else:
                # If no mapping_ids, update based on supplier_id (fallback)
                supplier_placeholders = ','.join(['?'] * len(awarded_suppliers))
                self.cursor.execute(f"""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET status = 'AWARDED'
                    WHERE rfq_id = ? AND supplier_id IN ({supplier_placeholders})
                """, (rfq_id, *list(awarded_suppliers)))
                
                self.cursor.execute(f"""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET status = 'LOST'
                    WHERE rfq_id = ? AND supplier_id NOT IN ({supplier_placeholders})
                    AND quotation_received = 1
                """, (rfq_id, *list(awarded_suppliers)))
            
            # Check if all items are fully awarded
            self.cursor.execute("""
                SELECT COUNT(*)
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ? AND quantity > ISNULL(awarded_quantity, 0)
            """, (rfq_id,))
            
            remaining_items = self.cursor.fetchone()[0]
            
            if remaining_items == 0:
                # All items fully awarded
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_headers]
                    SET status = 'COMPLETED'
                    WHERE rfq_id = ?
                """, (rfq_id,))
                
                # Update award summary
                self.cursor.execute("""
                    MERGE [RFQ].[rfq_award_summary] AS target
                    USING (SELECT ? AS rfq_id) AS source
                    ON target.rfq_id = source.rfq_id
                    WHEN MATCHED THEN
                        UPDATE SET award_status = 'FULLY_AWARDED',
                                 awarded_total = ?,
                                 currency = ?,
                                 awarded_at = GETDATE(),
                                 completed_at = GETDATE()
                    WHEN NOT MATCHED THEN
                        INSERT (rfq_id, award_status, awarded_total, currency, awarded_at, completed_at)
                        VALUES (?, 'FULLY_AWARDED', ?, ?, GETDATE(), GETDATE());
                """, (rfq_id, row[3], currency, rfq_id, row[3], currency))
            else:
                # Partially awarded
                self.cursor.execute("""
                    MERGE [RFQ].[rfq_award_summary] AS target
                    USING (SELECT ? AS rfq_id) AS source
                    ON target.rfq_id = source.rfq_id
                    WHEN MATCHED THEN
                        UPDATE SET award_status = 'PARTIALLY_AWARDED',
                                 awarded_total = ?,
                                 currency = ?,
                                 awarded_at = GETDATE()
                    WHEN NOT MATCHED THEN
                        INSERT (rfq_id, award_status, awarded_total, currency, awarded_at)
                        VALUES (?, 'PARTIALLY_AWARDED', ?, ?, GETDATE());
                """, (rfq_id, row[3], currency, rfq_id, row[3], currency))
            
            self.connection.commit()
            
            return {
                "status": "success",
                "message": "Proposal confirmed successfully",
                "rfq_id": rfq_id,
                "proposal_id": proposal_id,
                "total_amount": float(row[3]),
                "currency": currency,
                "awarded_suppliers": list(awarded_suppliers)
            }
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error confirming proposal: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_proposal_status(self, proposal_id: int, access_token: str) -> Dict[str, Any]:
        """
        Check the status of a proposal (for customer reference)
        """
        try:
            self.cursor.execute("""
                SELECT 
                    p.status,
                    p.responded_at,
                    p.response_notes,
                    p.expires_at,
                    p.total_amount,
                    p.currency
                FROM [RFQ].[rfq_customer_proposals] p
                WHERE p.proposal_id = ?
            """, (proposal_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Proposal not found"}
            
            # Note: We don't validate token here as it's just a status check
            # But you might want to add token validation for security
            
            is_expired = row[3] and datetime.now() > row[3]
            
            return {
                "status": "success",
                "proposal_status": "EXPIRED" if is_expired else row[0],
                "responded_at": row[1].isoformat() if row[1] else None,
                "response_notes": row[2],
                "expires_at": row[3].isoformat() if row[3] else None,
                "total_amount": float(row[4]) if row[4] else 0,
                "currency": row[5] or "USD",
                "is_expired": is_expired
            }
            
        except Exception as e:
            logger.error(f"Error getting proposal status: {str(e)}")
            return {"status": "error", "message": str(e)}