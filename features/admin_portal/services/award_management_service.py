# src/features/admin_portal/services/award_management_service.py

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from ....common.db_pyodbc import get_db_connection
from ....common.logging_config import get_logger
import secrets

logger = get_logger(__name__)

class AwardManagementService:
    """
    Service for managing per-product awards and customer confirmation workflow
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
    
    def get_award_candidates(self, rfq_id: str) -> Dict[str, Any]:
        """
        Get all line items with their bid candidates for award consideration
        This is what the admin sees when they click "Award Bid"
        """
        try:
            # Get RFQ header info
            self.cursor.execute("""
                SELECT 
                    rfq_id,
                    department,
                    status,
                    currency,
                    total_budget,
                    required_date,
                    delivery_deadline
                FROM [RFQ].[rfq_headers]
                WHERE rfq_id = ?
            """, (rfq_id,))
            
            header = self.cursor.fetchone()
            if not header:
                return {"status": "error", "message": "RFQ not found"}
            
            # Get all line items
            self.cursor.execute("""
                SELECT 
                    line_number,
                    category,
                    brand,
                    model,
                    part_number,
                    description,
                    quantity,
                    unit_price as estimated_unit_price,
                    total_price as estimated_total_price,
                    currency,
                    ISNULL(awarded_quantity, 0) as awarded_quantity,
                    ISNULL(pending_award_quantity, 0) as pending_award_quantity,
                    ISNULL(award_status, 'PENDING') as award_status
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (rfq_id,))
            
            items = []
            for row in self.cursor.fetchall():
                requested = float(row[6]) if row[6] else 0
                awarded = float(row[10]) if row[10] else 0
                pending = float(row[11]) if row[11] else 0
                available = requested - awarded - pending
                
                # Get bids for this line item from suppliers
                self.cursor.execute("""
                    SELECT 
                        rs.mapping_id,
                        rs.supplier_id,
                        s.company_name,
                        s.contact_person,
                        rs.quotation_amount,
                        rs.quotation_currency,
                        rs.status as bid_status,
                        rs.response_details,
                        rs.match_score,
                        rs.submitted_at
                    FROM [RFQ].[rfq_suppliers] rs
                    JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                    WHERE rs.rfq_id = ? AND rs.quotation_received = 1
                    AND rs.status NOT IN ('LOST', 'AWARDED')
                """, (rfq_id,))
                
                supplier_bids = []
                for bid_row in self.cursor.fetchall():
                    # Parse response_details to get line item specific bid
                    try:
                        bid_data = json.loads(bid_row[7]) if bid_row[7] else {}
                        quotations = bid_data.get('quotations', [])
                        
                        # Find quote for this line number
                        for quote in quotations:
                            if quote.get('line_number') == row[0]:
                                for product in quote.get('offered_products', []):
                                    # Check if this supplier already has pending awards for this line
                                    if pending > 0:
                                        # You might want to check if this supplier is part of pending awards
                                        pass
                                    
                                    supplier_bids.append({
                                        "mapping_id": bid_row[0],
                                        "supplier_id": bid_row[1],
                                        "company_name": bid_row[2],
                                        "contact_person": bid_row[3],
                                        "total_bid_amount": float(bid_row[4]) if bid_row[4] else 0,
                                        "currency": bid_row[5] or 'USD',
                                        "bid_status": bid_row[6],
                                        "match_score": float(bid_row[8]) if bid_row[8] else 0,
                                        "submitted_at": bid_row[9].isoformat() if bid_row[9] else None,
                                        "product_name": product.get('product_name', ''),
                                        "brand": product.get('brand', ''),
                                        "model": product.get('model', ''),
                                        "unit_price": float(product.get('unit_price', 0)),
                                        "quantity_offered": float(product.get('quantity', 0)),
                                        "total_price": float(product.get('total_price', 0)),
                                        "delivery_date": product.get('delivery_date'),
                                        "delivery_time_days": product.get('delivery_time_days')
                                    })
                    except Exception as e:
                        logger.error(f"Error parsing bid data for mapping_id {bid_row[0]}: {str(e)}")
                
                # Sort supplier bids by price (lowest first) and then by match score
                supplier_bids.sort(key=lambda x: (x['unit_price'], -x['match_score']))
                
                items.append({
                    "line_number": row[0],
                    "category": row[1] or "",
                    "brand": row[2] or "",
                    "model": row[3] or "",
                    "part_number": row[4] or "",
                    "description": row[5] or "",
                    "requested_quantity": requested,
                    "awarded_quantity": awarded,
                    "pending_quantity": pending,
                    "available_quantity": available,
                    "estimated_unit_price": float(row[7]) if row[7] else None,
                    "estimated_total_price": float(row[8]) if row[8] else None,
                    "currency": row[9] or "USD",
                    "award_status": row[12],
                    "supplier_bids": supplier_bids,
                    "can_award": available > 0 and len(supplier_bids) > 0
                })
            
            # Get customer email (you might need to get this from somewhere)
            customer_email = self._get_customer_email(rfq_id)
            
            return {
                "status": "success",
                "rfq_info": {
                    "rfq_id": header[0],
                    "department": header[1],
                    "status": header[2],
                    "currency": header[3] or "USD",
                    "total_budget": float(header[4]) if header[4] else 0,
                    "required_date": header[5].isoformat() if header[5] else None,
                    "delivery_deadline": header[6].isoformat() if header[6] else None
                },
                "items": items,
                "customer_email": customer_email,
                "total_items": len(items),
                "items_with_bids": len([i for i in items if i['supplier_bids']])
            }
            
        except Exception as e:
            logger.error(f"Error getting award candidates: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def _get_customer_email(self, rfq_id: str) -> Optional[str]:
        """Get customer email for this RFQ"""
        # try:
        #     self.cursor.execute("""
        #         SELECT email FROM [P8_NOAH_AI].[RFQ].[users] u
        #         JOIN [P8_NOAH_AI].[RFQ].[rfq_headers] h ON u.user_id = h.user_id
        #         WHERE h.rfq_id = ?
        #     """, (rfq_id,))
        #     row = self.cursor.fetchone()
        #     return row[0] if row else None
        # except:
        return None
    
    def create_award_proposal(self, rfq_id: str, awards: List[Dict], 
                            customer_email: str, notes: str = None) -> Dict[str, Any]:
        """
        Create a proposal with selected awards for customer confirmation
        awards: List of {
            'line_number': int,
            'supplier_id': int,
            'mapping_id': int (optional),
            'quantity': float,
            'unit_price': float
        }
        """
        try:
            # Validate awards
            if not awards:
                return {"status": "error", "message": "No awards selected"}
            
            # Check if all quantities are available
            for award in awards:
                self.cursor.execute("""
                    SELECT quantity, ISNULL(awarded_quantity, 0), ISNULL(pending_award_quantity, 0)
                    FROM [RFQ].[rfq_line_items]
                    WHERE rfq_id = ? AND line_number = ?
                """, (rfq_id, award['line_number']))
                
                row = self.cursor.fetchone()
                if not row:
                    return {"status": "error", "message": f"Line {award['line_number']} not found"}
                
                requested = float(row[0]) if row[0] else 0
                awarded = float(row[1]) if row[1] else 0
                pending = float(row[2]) if row[2] else 0
                available = requested - awarded - pending
                
                if award['quantity'] > available:
                    return {
                        "status": "error", 
                        "message": f"Line {award['line_number']}: Requested quantity {award['quantity']} exceeds available {available}"
                    }
            
            # Calculate total amount
            total_amount = sum(award['quantity'] * award['unit_price'] for award in awards)
            
            # Get RFQ currency
            self.cursor.execute("SELECT currency FROM [RFQ].[rfq_headers] WHERE rfq_id = ?", (rfq_id,))
            currency_row = self.cursor.fetchone()
            currency = currency_row[0] if currency_row else 'USD'
            
            # Generate access token for customer portal
            access_token = secrets.token_urlsafe(32)
            expires_at = datetime.now() + timedelta(days=7)
            
            # Create proposal
            proposal_data = {
                "rfq_id": rfq_id,
                "awards": awards,
                "total_amount": total_amount,
                "currency": currency,
                "created_at": datetime.now().isoformat(),
                "notes": notes,
                "access_token": access_token
            }
            
            self.cursor.execute("""
                INSERT INTO [RFQ].[rfq_customer_proposals]
                (rfq_id, proposal_data, total_amount, currency, status, 
                 sent_to_email, expires_at, created_at)
                OUTPUT INSERTED.proposal_id
                VALUES (?, ?, ?, ?, 'PENDING', ?, ?, GETDATE())
            """, (
                rfq_id,
                json.dumps(proposal_data, default=str),
                total_amount,
                currency,
                customer_email,
                expires_at
            ))
            
            proposal_id = self.cursor.fetchone()[0]
            
            # Insert proposal items and update pending quantities
            for award in awards:
                self.cursor.execute("""
                    INSERT INTO [RFQ].[rfq_proposal_items]
                    (proposal_id, line_number, supplier_id, awarded_quantity, 
                     unit_price, total_price, currency, supplier_mapping_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    proposal_id,
                    award['line_number'],
                    award['supplier_id'],
                    award['quantity'],
                    award['unit_price'],
                    award['quantity'] * award['unit_price'],
                    currency,
                    award.get('mapping_id')
                ))
                
                # Update pending quantities
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_line_items]
                    SET pending_award_quantity = ISNULL(pending_award_quantity, 0) + ?,
                        award_status = CASE 
                            WHEN (ISNULL(awarded_quantity, 0) + ISNULL(pending_award_quantity, 0) + ?) >= quantity 
                            THEN 'FULLY_PROPOSED'
                            ELSE 'PARTIALLY_PROPOSED'
                        END
                    WHERE rfq_id = ? AND line_number = ?
                """, (award['quantity'], award['quantity'], rfq_id, award['line_number']))
            
            self.connection.commit()
            
            return {
                "status": "success",
                "proposal_id": proposal_id,
                "message": "Award proposal created successfully",
                "access_token": access_token,  # Only for development/testing
                "expires_at": expires_at.isoformat()
            }
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error creating award proposal: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_pending_proposals(self, rfq_id: str = None) -> Dict[str, Any]:
        """
        Get all pending proposals (for admin view)
        """
        try:
            query = """
                SELECT 
                    p.proposal_id,
                    p.rfq_id,
                    p.total_amount,
                    p.currency,
                    p.status,
                    p.sent_to_email,
                    p.sent_at,
                    p.viewed_at,
                    p.expires_at,
                    p.created_at,
                    h.department,
                    COUNT(pi.proposal_item_id) as item_count
                FROM [RFQ].[rfq_customer_proposals] p
                JOIN [RFQ].[rfq_headers] h ON p.rfq_id = h.rfq_id
                LEFT JOIN [RFQ].[rfq_proposal_items] pi ON p.proposal_id = pi.proposal_id
                WHERE p.status = 'PENDING'
            """
            
            params = []
            if rfq_id:
                query += " AND p.rfq_id = ?"
                params.append(rfq_id)
            
            query += " GROUP BY p.proposal_id, p.rfq_id, p.total_amount, p.currency, p.status, p.sent_to_email, p.sent_at, p.viewed_at, p.expires_at, p.created_at, h.department ORDER BY p.created_at DESC"
            
            self.cursor.execute(query, params)
            
            proposals = []
            for row in self.cursor.fetchall():
                is_expired = row[8] and datetime.now() > row[8]
                
                proposals.append({
                    "proposal_id": row[0],
                    "rfq_id": row[1],
                    "total_amount": float(row[2]) if row[2] else 0,
                    "currency": row[3] or "USD",
                    "status": "EXPIRED" if is_expired else row[4],
                    "customer_email": row[5],
                    "sent_at": row[6].isoformat() if row[6] else None,
                    "viewed_at": row[7].isoformat() if row[7] else None,
                    "expires_at": row[8].isoformat() if row[8] else None,
                    "created_at": row[9].isoformat() if row[9] else None,
                    "department": row[10],
                    "item_count": row[11] or 0,
                    "is_expired": is_expired
                })
            
            return {
                "status": "success",
                "proposals": proposals,
                "total_count": len(proposals)
            }
            
        except Exception as e:
            logger.error(f"Error getting pending proposals: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def cancel_proposal(self, proposal_id: int) -> Dict[str, Any]:
        """
        Cancel a pending proposal and release pending quantities
        """
        try:
            # Get proposal details
            self.cursor.execute("""
                SELECT rfq_id, status, proposal_data
                FROM [RFQ].[rfq_customer_proposals]
                WHERE proposal_id = ?
            """, (proposal_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Proposal not found"}
            
            if row[1] != 'PENDING':
                return {"status": "error", "message": f"Proposal is already {row[1].lower()}"}
            
            # Get all proposal items to release pending quantities
            self.cursor.execute("""
                SELECT line_number, awarded_quantity
                FROM [RFQ].[rfq_proposal_items]
                WHERE proposal_id = ?
            """, (proposal_id,))
            
            for item in self.cursor.fetchall():
                # Release pending quantities
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_line_items]
                    SET pending_award_quantity = pending_award_quantity - ?,
                        award_status = 'PENDING'
                    WHERE rfq_id = ? AND line_number = ?
                """, (item[1], row[0], item[0]))
            
            # Update proposal status
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_customer_proposals]
                SET status = 'CANCELLED'
                WHERE proposal_id = ?
            """, (proposal_id,))
            
            self.connection.commit()
            
            return {
                "status": "success",
                "message": "Proposal cancelled successfully"
            }
            
        except Exception as e:
            self.connection.rollback()
            logger.error(f"Error cancelling proposal: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def get_award_selection_data(self, rfq_id: str) -> Dict[str, Any]:
        """
        Get data structure for per-product award selection with quantity inputs
        """
        try:
            # Get RFQ header info
            self.cursor.execute("""
                SELECT 
                    rfq_id,
                    department,
                    status,
                    currency,
                    total_budget,
                    required_date,
                    delivery_deadline
                FROM [RFQ].[rfq_headers]
                WHERE rfq_id = ?
            """, (rfq_id,))
            
            header = self.cursor.fetchone()
            if not header:
                return {"status": "error", "message": "RFQ not found"}
            
            # Get all line items
            self.cursor.execute("""
                SELECT 
                    line_number,
                    category,
                    brand,
                    model,
                    part_number,
                    description,
                    quantity,
                    unit_price as estimated_unit_price,
                    total_price as estimated_total_price,
                    currency,
                    ISNULL(awarded_quantity, 0) as awarded_quantity,
                    ISNULL(pending_award_quantity, 0) as pending_quantity,
                    ISNULL(award_status, 'PENDING') as award_status
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (rfq_id,))
            
            line_items_rows = self.cursor.fetchall()
            
            if not line_items_rows:
                return {"status": "error", "message": "No line items found for this RFQ"}
            
            # Get ONLY suppliers who have actually submitted bids (quotation_received = 1)
            self.cursor.execute("""
                SELECT 
                    rs.mapping_id,
                    rs.supplier_id,
                    s.company_name,
                    s.contact_person,
                    s.email,
                    rs.response_details,
                    rs.quotation_amount,
                    rs.quotation_currency,
                    rs.match_score,
                    rs.submitted_at
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                WHERE rs.rfq_id = ? 
                AND rs.quotation_received = 1  -- Only suppliers who submitted bids
                AND rs.status NOT IN ('LOST', 'AWARDED')
            """, (rfq_id,))
            
            supplier_rows = self.cursor.fetchall()
            print(f"Found {len(supplier_rows)} suppliers with bids")  # Debug print
            
            line_items = []
            total_requested_value = 0
            
            # For each line item, find matching bids from suppliers
            for row in line_items_rows:
                line_number = row[0]
                requested_qty = float(row[6]) if row[6] else 0
                awarded_qty = float(row[10]) if row[10] else 0
                pending_qty = float(row[11]) if row[11] else 0
                remaining_qty = requested_qty - awarded_qty - pending_qty
                currency = row[9] or header[3] or 'USD'
                
                # Calculate estimated value
                est_unit_price = float(row[7]) if row[7] else 0
                est_line_value = requested_qty * est_unit_price
                total_requested_value += est_line_value
                
                suppliers_for_line = []
                
                # Check each supplier's bid for this line item
                for supplier_row in supplier_rows:
                    mapping_id = supplier_row[0]
                    supplier_id = supplier_row[1]
                    company_name = supplier_row[2]
                    contact_person = supplier_row[3]
                    email = supplier_row[4]
                    response_details = supplier_row[5]
                    
                    print(f"Processing supplier {company_name} for line {line_number}")  # Debug
                    
                    if response_details:
                        try:
                            # Parse the JSON response
                            if isinstance(response_details, str):
                                bid_data = json.loads(response_details)
                            else:
                                bid_data = response_details
                            
                            # Look for this line number in line_item_bids (new format)
                            line_item_bids = bid_data.get('line_item_bids', [])
                            
                            for line_bid in line_item_bids:
                                if line_bid.get('line_number') == line_number:
                                    products_offered = line_bid.get('products_offered', [])
                                    
                                    for product in products_offered:
                                        unit_price = float(product.get('unit_price', 0))
                                        quantity_offered = float(product.get('quantity', 0))
                                        delivery_days = product.get('delivery_time_days')
                                        product_name = product.get('product_name', '')
                                        product_brand = product.get('brand', '')
                                        product_model = product.get('model', '')
                                        
                                        # Calculate match score
                                        match_score = self._calculate_match_score(
                                            unit_price, 
                                            est_unit_price, 
                                            delivery_days
                                        )
                                        
                                        # Calculate maximum award quantity
                                        max_award_qty = min(quantity_offered, remaining_qty)
                                        
                                        # Check for pending awards
                                        self.cursor.execute("""
                                            SELECT SUM(awarded_quantity)
                                            FROM [RFQ].[rfq_proposal_items] pi
                                            JOIN [RFQ].[rfq_customer_proposals] p ON pi.proposal_id = p.proposal_id
                                            WHERE p.rfq_id = ? 
                                            AND pi.line_number = ? 
                                            AND pi.supplier_id = ?
                                            AND p.status = 'PENDING'
                                        """, (rfq_id, line_number, supplier_id))
                                        
                                        pending_row = self.cursor.fetchone()
                                        already_pending = float(pending_row[0]) if pending_row and pending_row[0] else 0
                                        
                                        max_award_qty = max_award_qty - already_pending
                                        
                                        if max_award_qty > 0:
                                            suppliers_for_line.append({
                                                "mapping_id": mapping_id,
                                                "supplier_id": supplier_id,
                                                "company_name": company_name,
                                                "contact_person": contact_person,
                                                "email": email,
                                                "unit_price": unit_price,
                                                "total_bid_amount": float(supplier_row[6]) if supplier_row[6] else 0,
                                                "quantity_offered": quantity_offered,
                                                "already_pending": already_pending,
                                                "delivery_days": delivery_days,
                                                "match_score": match_score,
                                                "submitted_at": supplier_row[9].isoformat() if supplier_row[9] else None,
                                                "product_name": product_name,
                                                "brand": product_brand,
                                                "model": product_model,
                                                "selected": False,
                                                "award_quantity": 0,
                                                "max_award_quantity": max_award_qty,
                                                "min_award_quantity": 0,
                                                "can_award": max_award_qty > 0
                                            })
                                            print(f"  Added bid for line {line_number}: {company_name}, qty: {quantity_offered}, price: {unit_price}")  # Debug
                            
                            # Also check quotations format (backward compatibility)
                            quotations = bid_data.get('quotations', [])
                            for quote in quotations:
                                if quote.get('line_number') == line_number:
                                    for product in quote.get('offered_products', []):
                                        # Similar logic as above
                                        # ... (you can add this if needed)
                                        pass
                                        
                        except json.JSONDecodeError as e:
                            print(f"JSON parse error for supplier {company_name}: {str(e)}")
                            continue
                        except Exception as e:
                            print(f"Error processing supplier {company_name}: {str(e)}")
                            continue
                
                # Sort suppliers by price
                suppliers_for_line.sort(key=lambda x: (x['unit_price'], -x['match_score']))
                
                print(f"Line {line_number} has {len(suppliers_for_line)} bids")  # Debug
                
                line_items.append({
                    "line_number": line_number,
                    "category": row[1] or "",
                    "brand": row[2] or "",
                    "model": row[3] or "",
                    "part_number": row[4] or "",
                    "description": row[5] or f"{row[1] or 'Item'}",
                    "requested_quantity": requested_qty,
                    "awarded_quantity": awarded_qty,
                    "pending_quantity": pending_qty,
                    "remaining_quantity": remaining_qty,
                    "estimated_unit_price": est_unit_price,
                    "estimated_total_price": est_line_value,
                    "currency": currency,
                    "award_status": row[12],
                    "suppliers": suppliers_for_line,
                    "total_selected_quantity": 0,
                    "can_award": remaining_qty > 0 and len(suppliers_for_line) > 0,
                    "warning_message": None if remaining_qty > 0 else "This item is fully awarded or pending",
                    "selection_complete": False
                })
            
            return {
                "status": "success",
                "rfq_info": {
                    "rfq_id": header[0],
                    "department": header[1],
                    "status": header[2],
                    "currency": header[3] or "USD",
                    "total_budget": float(header[4]) if header[4] else 0,
                    "required_date": header[5].isoformat() if header[5] else None,
                    "delivery_deadline": header[6].isoformat() if header[6] else None,
                    "total_requested_value": total_requested_value
                },
                "line_items": line_items,
                "customer_email": None,
                "selection_guidelines": {
                    "allow_multiple_suppliers_per_item": True,
                    "quantity_splitting": True,
                    "default_checkbox_state": False,
                    "quantity_input_required": True
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting award selection data: {str(e)}")
            import traceback
            traceback.print_exc()
            return {"status": "error", "message": str(e)}

    def _calculate_match_score(self, unit_price, estimated_price, delivery_days):
        """Calculate match score based on price and delivery days"""
        try:
            score = 100
            
            # Price factor (lower price = higher score)
            if estimated_price and estimated_price > 0:
                price_ratio = unit_price / estimated_price
                if price_ratio > 1:
                    # More expensive than estimate
                    score -= (price_ratio - 1) * 50  # Reduce score for being over estimate
                else:
                    # Cheaper than estimate
                    score += (1 - price_ratio) * 30  # Bonus for being under estimate
            
            # Delivery factor (shorter delivery = higher score)
            if delivery_days:
                if delivery_days > 30:
                    score -= 20
                elif delivery_days > 20:
                    score -= 10
                elif delivery_days < 7:
                    score += 10
            
            return max(0, min(100, int(score)))  # Clamp between 0-100
        except:
            return 80  # Default score

    def validate_award_selection(self, rfq_id: str, selections: List[Dict]) -> Dict[str, Any]:
        """
        Validate the admin's award selections before creating proposal
        selections: List of {
            'line_number': int,
            'supplier_id': int,
            'award_quantity': float,
            'mapping_id': int (optional)
        }
        """
        try:
            validation_results = {
                "valid": True,
                "errors": [],
                "warnings": [],
                "line_items": {}
            }
            
            # Group selections by line number
            selections_by_line = {}
            for sel in selections:
                line_num = sel['line_number']
                if line_num not in selections_by_line:
                    selections_by_line[line_num] = []
                selections_by_line[line_num].append(sel)
            
            # Validate each line item
            for line_num, line_selections in selections_by_line.items():
                # Get line item details
                self.cursor.execute("""
                    SELECT quantity, 
                        ISNULL(awarded_quantity, 0), 
                        ISNULL(pending_award_quantity, 0)
                    FROM [RFQ].[rfq_line_items]
                    WHERE rfq_id = ? AND line_number = ?
                """, (rfq_id, line_num))
                
                row = self.cursor.fetchone()
                if not row:
                    validation_results['errors'].append(f"Line {line_num}: Not found")
                    validation_results['valid'] = False
                    continue
                
                requested = float(row[0]) if row[0] else 0
                awarded = float(row[1]) if row[1] else 0
                pending = float(row[2]) if row[2] else 0
                available = requested - awarded - pending
                
                # Calculate total selected quantity for this line
                total_selected = sum(sel['award_quantity'] for sel in line_selections)
                
                if total_selected > available:
                    validation_results['errors'].append(
                        f"Line {line_num}: Total selected quantity ({total_selected}) exceeds available ({available})"
                    )
                    validation_results['valid'] = False
                elif total_selected < available:
                    validation_results['warnings'].append(
                        f"Line {line_num}: Selected quantity ({total_selected}) is less than available ({available})"
                    )
                
                # Validate each supplier's quantity against their offered quantity
                for sel in line_selections:
                    supplier_id = sel['supplier_id']
                    award_qty = sel['award_quantity']
                    
                    if award_qty <= 0:
                        validation_results['errors'].append(
                            f"Line {line_num}: Award quantity must be greater than 0"
                        )
                        validation_results['valid'] = False
                        continue
                    
                    # Check supplier's offered quantity from rfq_line_item_bids
                    self.cursor.execute("""
                        SELECT quantity_offered 
                        FROM rfq_line_item_bids
                        WHERE rfq_id = ? AND line_number = ? AND supplier_id = ?
                    """, (rfq_id, line_num, supplier_id))
                    
                    bid_row = self.cursor.fetchone()
                    if bid_row:
                        offered_qty = float(bid_row[0]) if bid_row[0] else 0
                        if award_qty > offered_qty:
                            validation_results['errors'].append(
                                f"Line {line_num}, Supplier {supplier_id}: "
                                f"Award quantity ({award_qty}) exceeds offered quantity ({offered_qty})"
                            )
                            validation_results['valid'] = False
                
                validation_results['line_items'][line_num] = {
                    "requested": requested,
                    "awarded": awarded,
                    "pending": pending,
                    "available": available,
                    "selected": total_selected,
                    "remaining_after_selection": available - total_selected
                }
            
            return validation_results
            
        except Exception as e:
            logger.error(f"Error validating award selection: {str(e)}")
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": []
            }

    def create_award_proposal_from_selections(self, rfq_id: str, selections: List[Dict], 
                                        customer_email: str, notes: str = None) -> Dict[str, Any]:
        """
        Create award proposal from user selections
        selections: List of {
            'line_number': int,
            'supplier_id': int,
            'award_quantity': float,
            'unit_price': float,  # Will be fetched if not provided
            'mapping_id': int (optional)
        }
        """
        try:
            # First validate the selections
            validation = self.validate_award_selection(rfq_id, selections)
            if not validation['valid']:
                return {
                    "status": "error",
                    "message": "Validation failed",
                    "errors": validation['errors'],
                    "warnings": validation['warnings']
                }
            
            # Build awards list with complete information
            awards = []
            for sel in selections:
                line_num = sel['line_number']
                supplier_id = sel['supplier_id']
                award_qty = sel['award_quantity']
                
                # Get unit price and mapping_id if not provided
                if 'unit_price' not in sel or 'mapping_id' not in sel:
                    # Fetch from rfq_line_item_bids
                    self.cursor.execute("""
                        SELECT id as mapping_id, unit_price 
                        FROM rfq_line_item_bids
                        WHERE rfq_id = ? AND line_number = ? AND supplier_id = ?
                    """, (rfq_id, line_num, supplier_id))
                    
                    bid_row = self.cursor.fetchone()
                    if bid_row:
                        sel['mapping_id'] = bid_row[0]
                        sel['unit_price'] = float(bid_row[1]) if bid_row[1] else 0
                
                if 'unit_price' not in sel:
                    return {
                        "status": "error",
                        "message": f"Could not determine unit price for line {line_num}, supplier {supplier_id}"
                    }
                
                awards.append({
                    'line_number': line_num,
                    'supplier_id': supplier_id,
                    'mapping_id': sel.get('mapping_id'),
                    'quantity': award_qty,
                    'unit_price': sel['unit_price']
                })
            
            # Create the proposal using the existing method
            return self.create_award_proposal(
                rfq_id=rfq_id,
                awards=awards,
                customer_email=customer_email,
                notes=notes
            )
            
        except Exception as e:
            logger.error(f"Error creating proposal from selections: {str(e)}")
            return {"status": "error", "message": str(e)}